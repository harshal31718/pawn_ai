"""Tests for BYOK /keys routes and resolver per-user key lookup.

The Postgres-backed key_store is mocked — these tests verify routing, validation,
that key values are never returned to the client, and that the resolver only
ever uses a user's own BYOK key (no shared/fallback key of any kind).
"""

from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_list_keys_returns_providers_only(client):
    with patch("app.routes.keys.key_store.list_providers", return_value=["google", "groq"]):
        resp = client.get("/keys")
    assert resp.status_code == 200
    assert resp.json() == {"providers": ["google", "groq"]}


def test_set_key_stores_and_never_echoes_value(client):
    with patch("app.routes.keys.key_store.set_key") as mock_set:
        resp = client.put("/keys/groq", json={"api_key": "sk-secret-123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "ok", "provider": "groq"}
    assert "sk-secret-123" not in resp.text
    mock_set.assert_called_once_with("test-user-id", "groq", "sk-secret-123")


def test_set_key_rejects_unknown_provider(client):
    with patch("app.routes.keys.key_store.set_key") as mock_set:
        resp = client.put("/keys/notreal", json={"api_key": "x"})
    assert resp.status_code == 400
    mock_set.assert_not_called()


def test_set_key_rejects_empty_key(client):
    with patch("app.routes.keys.key_store.set_key") as mock_set:
        resp = client.put("/keys/google", json={"api_key": "   "})
    assert resp.status_code == 400
    mock_set.assert_not_called()


def test_delete_key(client):
    with patch("app.routes.keys.key_store.delete_key") as mock_del:
        resp = client.delete("/keys/google")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "provider": "google"}
    mock_del.assert_called_once_with("test-user-id", "google")


def test_resolver_uses_user_byok_key():
    """resolver.pick should key endpoints with the user's BYOK key."""
    from app.registry.loader import load_registry
    from app.core.rate_limiter import EndpointRateLimiter
    from app.resolver.resolver import Resolver

    registry = load_registry()
    rl = EndpointRateLimiter()
    resolver = Resolver(registry, rl)

    with patch("app.core.key_store.get_key", return_value="USER-BYOK-KEY") as mock_get:
        candidates = resolver.pick("google", user_id="user-1")

    # At least one google endpoint should carry the user's key in its auth header.
    assert candidates
    all_headers = " ".join(str(h) for (_, _, h, _, _) in candidates)
    assert "USER-BYOK-KEY" in all_headers
    mock_get.assert_called()


def test_resolver_raises_when_no_byok_key():
    """If the user has no BYOK key, resolver.pick raises (no fallback of any kind)."""
    from app.registry.loader import load_registry
    from app.core.rate_limiter import EndpointRateLimiter
    from app.resolver.resolver import Resolver
    from app.exceptions import NoEndpointError

    registry = load_registry()
    rl = EndpointRateLimiter()
    resolver = Resolver(registry, rl)

    with patch("app.core.key_store.get_key", return_value=None):
        with pytest.raises(NoEndpointError):
            resolver.pick("google", user_id="user-1")


# ── PAWN 2.0 Phase E.4: user_api_keys routes through SHARED_DB_DSN ─────────


def test_key_store_execute_wrapper_passes_shared_db_dsn():
    from app.core import key_store

    with patch("app.core.key_store.SHARED_DB_DSN", "postgresql://shared/db"), \
         patch("app.core.key_store.postgres_client.execute") as exec_mock:
        key_store.execute("delete from user_api_keys where user_id = %s", ("u1",))
    exec_mock.assert_called_once_with(
        "delete from user_api_keys where user_id = %s", ("u1",), dsn="postgresql://shared/db"
    )


def test_key_store_fetchone_wrapper_passes_shared_db_dsn():
    from app.core import key_store

    with patch("app.core.key_store.SHARED_DB_DSN", "postgresql://shared/db"), \
         patch("app.core.key_store.postgres_client.fetchone", return_value=None) as fetch_mock:
        key_store.fetchone("select 1")
    fetch_mock.assert_called_once_with("select 1", (), dsn="postgresql://shared/db")
