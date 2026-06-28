"""Tests for the Kaggle config routes and key_store round-trip.

The Supabase-backed store is mocked. These verify: the token is never returned,
validation, and that set_kaggle/get_kaggle round-trip a dict through real
AES-GCM encryption.
"""

from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_get_kaggle_not_configured(client):
    with patch("app.routes.keys.key_store.get_kaggle", return_value=None):
        resp = client.get("/keys/kaggle")
    assert resp.status_code == 200
    assert resp.json() == {"has_creds": False, "kernels": {}}


def test_get_kaggle_hides_token(client):
    cfg = {"username": "u", "api_token": "SECRET-TOKEN", "kernels": {"image": True}}
    with patch("app.routes.keys.key_store.get_kaggle", return_value=cfg):
        resp = client.get("/keys/kaggle")
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_creds"] is True
    assert body["kernels"] == {"image": True}
    assert "SECRET-TOKEN" not in resp.text


def test_put_kaggle_stores_and_never_echoes_token(client):
    with patch("app.routes.keys.key_store.set_kaggle") as mock_set:
        resp = client.put("/keys/kaggle", json={"username": "u", "api_token": "SECRET-TOKEN"})
    assert resp.status_code == 200
    assert "SECRET-TOKEN" not in resp.text
    mock_set.assert_called_once_with("test-user-id", {"username": "u", "api_token": "SECRET-TOKEN"})


def test_put_kaggle_rejects_empty(client):
    with patch("app.routes.keys.key_store.set_kaggle") as mock_set:
        resp = client.put("/keys/kaggle", json={"username": "  ", "api_token": "x"})
    assert resp.status_code == 400
    mock_set.assert_not_called()


def test_delete_kaggle(client):
    with patch("app.routes.keys.key_store.delete_kaggle") as mock_del:
        resp = client.delete("/keys/kaggle")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    mock_del.assert_called_once_with("test-user-id")


def test_kaggle_store_roundtrip():
    """set_kaggle then get_kaggle returns the same dict, through real crypto."""
    from app.core import key_store

    class FakeResult:
        def __init__(self, data):
            self.data = data

    class FakeTable:
        def __init__(self, store):
            self.store = store
            self._mode = None

        def upsert(self, row):
            self.store["row"] = row
            self._mode = "upsert"
            return self

        def select(self, *a):
            self._mode = "select"
            return self

        def delete(self):
            self._mode = "delete"
            return self

        def eq(self, *a):
            return self

        def single(self):
            return self

        def execute(self):
            if self._mode == "select":
                return FakeResult(self.store.get("row"))
            return FakeResult(None)

    class FakeDB:
        def __init__(self, store):
            self.store = store

        def table(self, name):
            return FakeTable(self.store)

    store: dict = {}
    cfg = {"username": "alice", "api_token": "tok-123", "kernels": {"cube": True}}
    with patch("app.core.key_store.get_db", return_value=FakeDB(store)):
        key_store.set_kaggle("user-1", cfg)
        # The persisted value must be encrypted (no plaintext token on disk).
        assert "tok-123" not in store["row"]["key_enc"]
        got = key_store.get_kaggle("user-1")
    assert got == cfg
