"""Login-change plan: PUT /account/password.

Auth is bypassed by conftest.py's autouse fixture (every request gets
user_id="test-user-id") -- these tests mock fetchone/execute directly,
matching test_admin_routes.py's convention.
"""
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app.core.password_utils import hash_password
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_change_password_succeeds_with_correct_current_password(client):
    row = {"password_hash": hash_password("old-password")}
    with patch("app.routes.account.fetchone", return_value=row), \
         patch("app.routes.account.execute") as exec_mock:
        resp = client.put(
            "/account/password",
            json={"current_password": "old-password", "new_password": "new-password-123"},
        )
    assert resp.status_code == 200
    exec_mock.assert_called_once()


def test_change_password_rejects_wrong_current_password(client):
    row = {"password_hash": hash_password("old-password")}
    with patch("app.routes.account.fetchone", return_value=row), \
         patch("app.routes.account.execute") as exec_mock:
        resp = client.put(
            "/account/password",
            json={"current_password": "not-the-old-password", "new_password": "new-password-123"},
        )
    assert resp.status_code == 401
    exec_mock.assert_not_called()


def test_change_password_rejects_new_password_too_short(client):
    row = {"password_hash": hash_password("old-password")}
    with patch("app.routes.account.fetchone", return_value=row), \
         patch("app.routes.account.execute") as exec_mock:
        resp = client.put(
            "/account/password",
            json={"current_password": "old-password", "new_password": "short"},
        )
    assert resp.status_code == 400
    exec_mock.assert_not_called()


def test_change_password_404_style_401_when_user_row_missing(client):
    """No row / no password_hash set at all (shouldn't happen post-Google-
    signup, but defensive) -- treated as an auth failure, not a crash."""
    with patch("app.routes.account.fetchone", return_value=None):
        resp = client.put(
            "/account/password",
            json={"current_password": "anything", "new_password": "new-password-123"},
        )
    assert resp.status_code == 401
