"""Login-change plan: PUT /account/password.

Auth is bypassed by conftest.py's autouse fixture (every request gets
user_id="test-user-id") -- these tests mock execute directly, matching
test_admin_routes.py's convention. No current-password check -- the active
(already-authenticated) session is the auth, so this doubles as both
"change" and "forgot" from within Settings.
"""
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_change_password_succeeds(client):
    with patch("app.routes.account.execute") as exec_mock:
        resp = client.put(
            "/account/password",
            json={"new_password": "new-password-123"},
        )
    assert resp.status_code == 200
    exec_mock.assert_called_once()


def test_change_password_rejects_new_password_too_short(client):
    with patch("app.routes.account.execute") as exec_mock:
        resp = client.put(
            "/account/password",
            json={"new_password": "short"},
        )
    assert resp.status_code == 400
    exec_mock.assert_not_called()
