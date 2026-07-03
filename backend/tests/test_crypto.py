"""Tests for the GET /crypto/salt route.

The salt is public (PBKDF2 salt) but must be stable per user and idempotent.
Drive is mocked; the local-fallback path is exercised with a tmp DATA_DIR.
"""

import base64
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _is_b64_16_bytes(s: str) -> bool:
    try:
        return len(base64.b64decode(s)) == 16
    except Exception:
        return False


def test_salt_created_on_drive_when_missing(client):
    fake_drive = type("D", (), {})()
    fake_drive.get_or_create_root = lambda: "root-id"
    fake_drive.download_text_by_name = lambda name, folder: None
    uploaded = {}
    fake_drive.upload_text = lambda name, content, folder: uploaded.update(
        {"name": name, "content": content, "folder": folder}
    )

    with patch("app.routes.crypto.get_drive_for_user", return_value=fake_drive):
        resp = client.get("/crypto/salt")

    assert resp.status_code == 200
    salt = resp.json()["salt"]
    assert _is_b64_16_bytes(salt)
    # Wrote it back to Drive under the hidden .salt file at the PAWN root.
    assert uploaded["name"] == ".salt"
    assert uploaded["content"] == salt
    assert uploaded["folder"] == "root-id"


def test_salt_returns_existing_drive_value(client):
    existing = base64.b64encode(b"0123456789abcdef").decode()
    fake_drive = type("D", (), {})()
    fake_drive.get_or_create_root = lambda: "root-id"
    fake_drive.download_text_by_name = lambda name, folder: existing
    fake_drive.upload_text = lambda *a, **k: pytest.fail("must not rewrite salt")

    with patch("app.routes.crypto.get_drive_for_user", return_value=fake_drive):
        resp = client.get("/crypto/salt")

    assert resp.status_code == 200
    assert resp.json()["salt"] == existing


def test_salt_local_fallback_is_idempotent(client, tmp_path):
    with patch("app.routes.crypto.get_drive_for_user", return_value=None), patch(
        "app.routes.crypto._LOCAL_SALT_DIR", tmp_path / "salts"
    ):
        first = client.get("/crypto/salt").json()["salt"]
        second = client.get("/crypto/salt").json()["salt"]

    assert _is_b64_16_bytes(first)
    assert first == second  # stable across calls for the same user
