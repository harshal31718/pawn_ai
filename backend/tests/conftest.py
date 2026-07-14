"""Shared pytest fixtures and configuration.

Auth middleware is bypassed for all tests: every request gets
request.state.user_id = "test-user-id" without a real JWT.
"""

import os
import tempfile
import pytest
from unittest.mock import patch

# Set secrets needed for config imports before any app code runs
os.environ.setdefault("JWT_SECRET", "0" * 64)
os.environ.setdefault("ENCRYPTION_SECRET", "0" * 64)
os.environ.setdefault("POSTGRES_DSN", "postgresql://test:test@localhost:5432/test")

# Isolate every test worker's app.constants.DATA_DIR (registry/memory/rate-limits/
# checkpoints.db) away from the real dev data volume (docker-compose.yml bind-mounts
# ./backend/data:/app/data from the host). Every test module that needs the /chat
# graph builds its own `client` fixture via `with TestClient(app) as c:`, which runs
# app_initializer.initialize_managers()'s real AsyncSqliteSaver.from_conn_string()
# against CHECKPOINTS_DB on every single test. Under `pytest -n auto` (mandated by
# testing.md for the full-suite gate) that's many parallel xdist worker processes all
# opening/closing the SAME sqlite file concurrently on a Docker-Desktop-for-Windows
# bind mount -- a well-known SQLite/bind-mount locking incompatibility, reproduced
# live 2026-07-14 as `sqlite3.OperationalError: unable to open database file` across
# every test that actually invokes /chat (16 failures, previously misattributed to a
# sandbox-only langchain-core version artifact -- that explanation was wrong; this is
# the real cause and reproduces in real Docker). Fix: give each xdist worker ("gw0",
# "gw1", ... or "master" when run without -n) its own throwaway temp DATA_DIR, set
# BEFORE any `app.*` module is imported (conftest.py always loads first). Safe: no
# test relies on real seed data surviving here -- `registry.loader.load_registry()`
# calls `seed_registry()`, which writes fresh models.json/endpoints.json into
# whatever REGISTRY_DIR it finds empty.
_worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
os.environ.setdefault("PAWN_DATA_DIR", os.path.join(tempfile.gettempdir(), f"pawn_test_data_{_worker_id}"))


TEST_USER_ID = "test-user-id"
TEST_EMAIL = "test@example.com"


@pytest.fixture(autouse=True)
def bypass_auth():
    """Stub AuthMiddleware.dispatch so all test requests have a user_id set."""
    from app.middleware.auth import AuthMiddleware

    async def _mock_dispatch(self, request, call_next):
        request.state.user_id = TEST_USER_ID
        request.state.email = TEST_EMAIL
        return await call_next(request)

    with patch.object(AuthMiddleware, "dispatch", _mock_dispatch):
        yield


@pytest.fixture(autouse=True)
def stub_byok_key():
    """Provider keys are now BYOK-only (no shared-secret fallback). Give the test
    user a key for every provider so resolver.pick() returns endpoints. Tests that
    assert the no-key path can override this with a narrower patch."""
    with patch("app.core.key_store.get_key", return_value="TEST-BYOK-KEY"):
        yield
