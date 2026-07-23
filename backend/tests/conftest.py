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
#
# mkdtemp(), not a fixed gettempdir()/pawn_test_data_<worker> path (2026-07-14
# follow-up): a fixed path is stable *within* one `pytest` run but persists in the
# container's /tmp *across* separate `docker compose exec backend pytest` invocations
# -- so the first run seeds registry/models.json once, and every later run's
# seed_registry() finds it "already exists" and never rewrites it, even after
# INITIAL_MODELS/INITIAL_ENDPOINTS change (exactly what happened: the seed-data-drift
# fix landed, but a still-running container's leftover /tmp/pawn_test_data_gw16 from
# before the fix kept serving the stale data on the next run). mkdtemp() generates a
# fresh, uniquely-named directory every time this module loads -- i.e. every `pytest`
# process start -- so there is never a stale leftover to find.
_worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
os.environ.setdefault("PAWN_DATA_DIR", tempfile.mkdtemp(prefix=f"pawn_test_data_{_worker_id}_"))


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


@pytest.fixture(autouse=True)
def stub_pool_keys(request):
    """Default every test to an EMPTY operator pool (no shared pool keys).

    The resolver/dashboard read pool keys live from the real dev Postgres
    (`config.read_pool_key` -> `pool_key_store.get_pool_config` -> the
    `pool_api_keys` table), which is NOT test-isolated. When an admin
    configures a pool key via the live Admin UI (e.g. google/groq, 2026-07-23),
    every resolver/keys/capability test that assumed "no pool" and didn't mock
    it silently started failing -- the same class of real-DB leakage as the
    rate-limiter seed.

    Patched at the `get_pool_config` seam (returns None = "no DB row"), NOT at
    `read_pool_key` itself, so `read_pool_key`'s real logic still runs (this is
    exactly the historical empty-`pool_api_keys`-table state that let these
    tests pass). Tests that exercise the pool path override cleanly:
    `test_pool_keys.py` patches `app.config.read_pool_key`/`get_pool_config`
    itself; `test_pool_key_store.py` unit-tests the REAL `get_pool_config` (it
    isolates at the lower `fetchone`/`fetchall` seam), so this fixture skips
    that module entirely rather than clobbering the function it's testing."""
    if request.module.__name__.endswith("test_pool_key_store"):
        yield
        return
    with patch("app.core.pool_key_store.get_pool_config", return_value=None):
        yield
