"""Phase 1b: two-tier keys (BYOK + self-hosted free pool).

Covers Resolver._resolve_key's key_source precedence and the dashboard's
per-row key_source reporting. Registry under test is the seeded fixture
(app/registry/seed.py) via load_registry() -- same convention as
test_capability_routing.py / test_resolver.py.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app.core.rate_limiter import EndpointRateLimiter
from app.registry.loader import load_registry
from app.resolver.resolver import Resolver


def _resolver():
    return Resolver(load_registry(), EndpointRateLimiter())


def _ep(key_source, provider="groq"):
    return SimpleNamespace(provider=provider, key_source=key_source)


# ── Resolver._resolve_key: key_source precedence ────────────────────────────


def test_byok_uses_only_the_users_own_key():
    r = _resolver()
    with patch("app.core.key_store.get_key", return_value="byok-key"), \
         patch("app.config.read_pool_key", return_value="pool-key"):
        assert r._resolve_key(_ep("byok"), "u1") == "byok-key"


def test_byok_never_falls_back_to_pool():
    r = _resolver()
    with patch("app.core.key_store.get_key", return_value=None), \
         patch("app.config.read_pool_key", return_value="pool-key"):
        assert r._resolve_key(_ep("byok"), "u1") == ""


def test_pool_only_uses_pool_even_if_byok_exists():
    """A "pool"-only endpoint deliberately ignores the user's own key -- a
    lever for forcing specific models onto the operator's pool. Not used by
    any shipped endpoint yet, but the mechanism must work in isolation."""
    r = _resolver()
    with patch("app.core.key_store.get_key", return_value="byok-key"), \
         patch("app.config.read_pool_key", return_value="pool-key"):
        assert r._resolve_key(_ep("pool"), "u1") == "pool-key"


def test_pool_only_never_falls_back_to_byok():
    r = _resolver()
    with patch("app.core.key_store.get_key", return_value="byok-key"), \
         patch("app.config.read_pool_key", return_value=None):
        assert r._resolve_key(_ep("pool"), "u1") == ""


def test_either_prefers_byok_when_both_available():
    """PAWN 2.0 Phase A.1 precedence (2026-07-23, reverses Phase 1b): BYOK
    FIRST, pool as fallback -- a user who brings their own key is never
    displaced onto the shared pool, which exists only for keyless users."""
    r = _resolver()
    with patch("app.core.key_store.get_key", return_value="byok-key"), \
         patch("app.config.read_pool_key", return_value="pool-key"):
        assert r._resolve_key(_ep("either"), "u1") == "byok-key"


def test_either_falls_back_to_pool_when_byok_unconfigured():
    r = _resolver()
    with patch("app.core.key_store.get_key", return_value=None), \
         patch("app.config.read_pool_key", return_value="pool-key"):
        assert r._resolve_key(_ep("either"), "u1") == "pool-key"


def test_keyed_user_never_consumes_the_pool():
    """Regression for Phase A.1: even when the pool key is checked first in
    a naive implementation, a user who holds their own key for this provider
    must resolve to it -- never silently spend the shared pool's quota on
    their behalf."""
    r = _resolver()
    with patch("app.core.key_store.get_key", return_value="byok-key") as get_key, \
         patch("app.config.read_pool_key", return_value="pool-key") as read_pool:
        result = r._resolve_key(_ep("either"), "u1")
    assert result == "byok-key"
    get_key.assert_called_once()


def test_either_empty_when_neither_available():
    r = _resolver()
    with patch("app.core.key_store.get_key", return_value=None), \
         patch("app.config.read_pool_key", return_value=None):
        assert r._resolve_key(_ep("either"), "u1") == ""


def test_either_pool_usable_with_no_user_id():
    """A user with no BYOK key at all (or an anonymous/internal caller) can
    still reach a pool-backed endpoint -- this is the whole point of the pool:
    it doesn't require the caller to have configured anything themselves."""
    r = _resolver()
    with patch("app.core.key_store.get_key", return_value=None), \
         patch("app.config.read_pool_key", return_value="pool-key"):
        assert r._resolve_key(_ep("either"), None) == "pool-key"


def test_endpoint_missing_key_source_attribute_defaults_to_byok():
    """Defensive: _resolve_key uses getattr(ep, "key_source", "byok") rather
    than ep.key_source directly, so a caller passing a plain object without
    the attribute at all (not just Pydantic's own default) still behaves
    exactly like a "byok" endpoint instead of raising AttributeError."""
    bare_ep = SimpleNamespace(provider="groq")  # no key_source attribute
    r = _resolver()
    with patch("app.core.key_store.get_key", return_value="byok-key"), \
         patch("app.config.read_pool_key", return_value="pool-key"):
        assert r._resolve_key(bare_ep, "u1") == "byok-key"


# ── config.read_pool_key ─────────────────────────────────────────────────────
# PAWN 2.0 Phase B.4: DB-first (pool_key_store), Docker-secret/env-var as a
# bootstrap fallback when no DB row exists for the provider. No more
# @lru_cache to clear -- pool_key_store's own short-TTL cache replaced it.


def test_read_pool_key_reads_env_var_fallback(monkeypatch):
    from app.config import read_pool_key
    monkeypatch.setenv("POOL_TESTPROV_API_KEY", "secret-value")
    with patch("app.core.pool_key_store.get_pool_config", return_value=None):
        assert read_pool_key("testprov") == "secret-value"


def test_read_pool_key_none_when_unconfigured(monkeypatch):
    from app.config import read_pool_key
    monkeypatch.delenv("POOL_UNSETPROV_API_KEY", raising=False)
    with patch("app.core.pool_key_store.get_pool_config", return_value=None):
        assert read_pool_key("unsetprov") is None


def test_read_pool_key_prefers_db_row_over_secret_or_env(monkeypatch):
    """DB-first: even when a Docker secret/env var is also configured, an
    existing (enabled) DB row wins."""
    from app.config import read_pool_key
    monkeypatch.setenv("POOL_TESTPROV_API_KEY", "env-value")
    with patch("app.core.pool_key_store.get_pool_config", return_value={"enabled": True}), \
         patch("app.core.pool_key_store.get_pool_key", return_value="db-value"):
        assert read_pool_key("testprov") == "db-value"


def test_read_pool_key_none_when_db_row_disabled_even_with_secret_fallback(monkeypatch):
    """A disabled DB row is a deliberate admin choice -- must not silently
    fall through to the Docker-secret bootstrap value."""
    from app.config import read_pool_key
    monkeypatch.setenv("POOL_TESTPROV_API_KEY", "env-value")
    with patch("app.core.pool_key_store.get_pool_config", return_value={"enabled": False}), \
         patch("app.core.pool_key_store.get_pool_key", return_value=None):
        assert read_pool_key("testprov") is None


# ── dashboard: per-row key_source reflects what's actually usable ──────────


@pytest.fixture()
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


def _keys(*allowed):
    allowed_set = set(allowed)
    return patch(
        "app.routes.dashboard.key_store.get_key",
        side_effect=lambda user_id, provider: "KEY" if provider in allowed_set else None,
    )


def _pool(*allowed):
    """Patch app.routes.dashboard's read_pool_key so only `allowed` providers
    have an operator pool key configured."""
    allowed_set = set(allowed)
    return patch(
        "app.routes.dashboard.read_pool_key",
        side_effect=lambda provider: "POOL-KEY" if provider in allowed_set else None,
    )


def test_pool_key_alone_surfaces_a_row_with_no_byok_key(client):
    """The whole point of the pool: a user with ZERO keys of their own can
    still see (and use) an endpoint the operator has pool-funded."""
    with _keys(), _pool("google"):
        resp = client.get("/dashboard/free-tiers")
    assert resp.status_code == 200
    body = resp.json()
    google_rows = [r for r in body["rows"] if r["provider"] == "google"]
    assert google_rows, "expected a google row from the pool key alone"
    assert all(r["key_source"] == "pool" for r in google_rows)


def test_byok_preferred_over_pool_in_key_source_label(client):
    """Matches the resolver's PAWN 2.0 Phase A.2 precedence: when both a BYOK
    key and a pool key are available for the same provider, the row must
    report "byok" (what's actually being drawn on), not "pool"."""
    with _keys("google"), _pool("google"):
        resp = client.get("/dashboard/free-tiers")
    body = resp.json()
    google_rows = [r for r in body["rows"] if r["provider"] == "google"]
    assert google_rows
    assert all(r["key_source"] == "byok" for r in google_rows)


def test_byok_row_reported_when_no_pool_key_configured(client):
    with _keys("groq"), _pool():
        resp = client.get("/dashboard/free-tiers")
    body = resp.json()
    groq_rows = [r for r in body["rows"] if r["provider"] == "groq"]
    assert groq_rows
    assert all(r["key_source"] == "byok" for r in groq_rows)


def test_neither_key_source_excludes_the_row_entirely(client):
    with _keys(), _pool():
        resp = client.get("/dashboard/free-tiers")
    body = resp.json()
    assert body["rows"] == []
