"""Shared pytest fixtures and configuration.

Auth middleware is bypassed for all tests: every request gets
request.state.user_id = "test-user-id" without a real JWT.
"""

import os
import pytest
from unittest.mock import patch

# Set secrets needed for config imports before any app code runs
os.environ.setdefault("JWT_SECRET", "0" * 64)
os.environ.setdefault("ENCRYPTION_SECRET", "0" * 64)
os.environ.setdefault("POSTGRES_DSN", "postgresql://test:test@localhost:5432/test")


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
