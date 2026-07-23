"""PAWN 2.0 Phase B.5: /admin/* routes -- gated by require_admin, so every
route must 403 for a non-admin caller regardless of what it does, and 200 for
the admin email.

conftest.py's autouse bypass_auth fixture replaces AuthMiddleware.dispatch
entirely, hardcoding request.state.email to TEST_EMAIL ("test@example.com")
for every test in the suite -- so by default every request here IS a
non-admin caller (test_non_admin_gets_403 needs no extra setup). For the
admin-path tests, patch app.core.admin.ADMIN_EMAIL down to TEST_EMAIL instead
of trying to override AuthMiddleware per-test: Starlette's
BaseHTTPMiddleware binds `self.dispatch` once when the middleware stack is
first built (cached on the shared `app` object across the whole test
session), so a second, test-scoped patch.object on top of conftest's
already-bound instance is silently ineffective -- confirmed by trial, not
assumed.
"""

from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app.main import app

TEST_EMAIL = "test@example.com"  # must match conftest.TEST_EMAIL


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _as_admin():
    return patch("app.core.admin.ADMIN_EMAIL", TEST_EMAIL)


# ── require_admin gate: every route 403s for a non-admin ────────────────────


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/admin/pool-keys"),
        ("PUT", "/admin/pool-keys/groq"),
        ("DELETE", "/admin/pool-keys/groq"),
        ("PATCH", "/admin/pool-keys/groq"),
        ("GET", "/admin/stats"),
    ],
)
def test_non_admin_gets_403(client, method, path):
    resp = client.request(method, path, json={"api_key": "x"})
    assert resp.status_code == 403


# ── admin CRUD ────────────────────────────────────────────────────────────


def test_admin_lists_pool_keys(client):
    rows = [{"provider": "groq", "enabled": True, "saturation_pct": None}]
    with _as_admin(), patch("app.routes.admin.pool_key_store.list_pool_providers", return_value=rows):
        resp = client.get("/admin/pool-keys")
    assert resp.status_code == 200
    body = resp.json()
    assert body["providers"] == [
        {"provider": "groq", "configured": True, "enabled": True, "saturation_pct": None}
    ]


def test_admin_sets_pool_key(client):
    with _as_admin(), patch("app.routes.admin.pool_key_store.set_pool_key") as set_mock:
        resp = client.put("/admin/pool-keys/groq", json={"api_key": "real-key"})
    assert resp.status_code == 200
    set_mock.assert_called_once_with("groq", "real-key")


def test_admin_rejects_unknown_provider(client):
    with _as_admin():
        resp = client.put("/admin/pool-keys/not-a-real-provider", json={"api_key": "x"})
    assert resp.status_code == 400


def test_admin_rejects_empty_key(client):
    with _as_admin():
        resp = client.put("/admin/pool-keys/groq", json={"api_key": "  "})
    assert resp.status_code == 400


def test_admin_deletes_pool_key(client):
    with _as_admin(), patch("app.routes.admin.pool_key_store.delete_pool_key") as del_mock:
        resp = client.delete("/admin/pool-keys/groq")
    assert resp.status_code == 200
    del_mock.assert_called_once_with("groq")


def test_admin_patches_enabled_and_saturation(client):
    with _as_admin(), \
         patch("app.routes.admin.pool_key_store.get_pool_config", return_value={"enabled": True}), \
         patch("app.routes.admin.pool_key_store.set_enabled") as set_enabled, \
         patch("app.routes.admin.pool_key_store.set_saturation_pct") as set_sat:
        resp = client.patch(
            "/admin/pool-keys/groq",
            json={"enabled": False, "saturation_pct": 90},
        )
    assert resp.status_code == 200
    set_enabled.assert_called_once_with("groq", False)
    set_sat.assert_called_once_with("groq", 90)


def test_admin_patch_404_when_no_row(client):
    with _as_admin(), patch("app.routes.admin.pool_key_store.get_pool_config", return_value=None):
        resp = client.patch("/admin/pool-keys/groq", json={"enabled": False})
    assert resp.status_code == 404


def test_admin_stats_returns_registered_user_count(client):
    with _as_admin(), patch("app.routes.admin.fetchone", return_value={"n": 7}):
        resp = client.get("/admin/stats")
    assert resp.status_code == 200
    assert resp.json() == {"registered_users": 7}
