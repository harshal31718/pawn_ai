"""Tests for auth routes — focus on GET /auth/drive/status.

/auth/* bypasses AuthMiddleware, so the endpoint decodes the Bearer token
itself; these tests pass a real JWT (JWT_SECRET is stubbed in conftest) and
mock drive_factory.get_drive_for_user. The status must reflect real Drive
usability, not just token presence — so a linked-but-unusable Drive (scope
declined → get_or_create_root raises) reports connected: false.
"""

from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from app.core.jwt_utils import create_token
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_drive_status_requires_token(client):
    resp = client.get("/auth/drive/status")
    assert resp.status_code == 401


def test_drive_status_rejects_bad_token(client):
    resp = client.get("/auth/drive/status", headers=_auth("not-a-jwt"))
    assert resp.status_code == 401


def test_drive_status_false_when_not_linked(client):
    token = create_token("user-1", "u1@example.com")
    with patch("app.core.drive_factory.get_drive_for_user", return_value=None):
        resp = client.get("/auth/drive/status", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == {"connected": False}


def test_drive_status_true_when_usable(client):
    token = create_token("user-1", "u1@example.com")
    drive = MagicMock()
    drive.get_or_create_root.return_value = "root-folder-id"
    with patch("app.core.drive_factory.get_drive_for_user", return_value=drive):
        resp = client.get("/auth/drive/status", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == {"connected": True}
    drive.get_or_create_root.assert_called_once()


def test_drive_status_false_when_scope_declined(client):
    """Token exists but drive.file was never granted → the Drive call fails →
    connected: false (the exact false-positive this endpoint guards against)."""
    token = create_token("user-1", "u1@example.com")
    drive = MagicMock()
    drive.get_or_create_root.side_effect = Exception("insufficient scope")
    with patch("app.core.drive_factory.get_drive_for_user", return_value=drive):
        resp = client.get("/auth/drive/status", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == {"connected": False}


# ── PAWN 2.0 Phase B.1: GET /auth/me carries an is_admin flag ───────────────


def test_me_reports_is_admin_false_for_a_regular_user(client):
    token = create_token("user-1", "u1@example.com")
    row = {"user_id": "user-1", "email": "u1@example.com", "name": "U1"}
    with patch("app.routes.auth.fetchone", return_value=row):
        resp = client.get("/auth/me", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["is_admin"] is False


def test_me_reports_is_admin_true_for_the_admin_email(client):
    from app.constants import ADMIN_EMAIL

    token = create_token("admin-1", ADMIN_EMAIL)
    row = {"user_id": "admin-1", "email": ADMIN_EMAIL, "name": "Admin"}
    with patch("app.routes.auth.fetchone", return_value=row):
        resp = client.get("/auth/me", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["is_admin"] is True


def test_me_404_when_user_row_missing(client):
    token = create_token("user-404", "gone@example.com")
    with patch("app.routes.auth.fetchone", return_value=None):
        resp = client.get("/auth/me", headers=_auth(token))
    assert resp.status_code == 404
