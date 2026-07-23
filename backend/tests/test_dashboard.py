"""R3: GET /dashboard/free-tiers.

Auth is bypassed by conftest.py (every request gets user_id="test-user-id");
key_store.get_key is patched to control exactly which providers "this user"
holds a key for, and the rate limiter's real snapshot() is used with real
recorded usage so the aggregate math is exercised end-to-end rather than mocked
away.
"""
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _keys(*allowed):
    allowed_set = set(allowed)
    return patch(
        "app.routes.dashboard.key_store.get_key",
        side_effect=lambda user_id, provider: "KEY" if provider in allowed_set else None,
    )


def test_no_keys_returns_empty_dashboard_not_an_error(client):
    """An empty dashboard is the correct state for 'no keys configured yet' --
    mirrors how Resolver.pick() treats a keyless user (a clear error only when
    a MODEL is actually requested, never when just listing)."""
    with _keys():
        resp = client.get("/dashboard/free-tiers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["rows"] == []
    assert body["total_tokens_remaining_today"] is None
    assert body["uncapped_providers"] == []


def test_only_keyed_providers_appear(client):
    with _keys("google"):
        resp = client.get("/dashboard/free-tiers")
    body = resp.json()
    assert body["rows"], "expected at least one Google-backed row"
    assert all(r["provider"] == "google" for r in body["rows"])


def test_capped_endpoint_reports_remaining(client):
    with _keys("cerebras"):
        resp = client.get("/dashboard/free-tiers")
    body = resp.json()
    capped = [r for r in body["rows"] if r["has_published_cap"]]
    assert capped, "expected at least one cerebras endpoint with a tpd_limit"
    row = capped[0]
    assert row["tpd_remaining"] == row["tpd_limit"] - row["tpd_used"]


def test_usage_reduces_remaining(client):
    """Exercises the real rate limiter, not a mock -- proves the aggregate
    actually reflects recorded usage."""
    with _keys("cerebras"):
        before = client.get("/dashboard/free-tiers").json()
        capped_before = next(r for r in before["rows"] if r["has_published_cap"])

        rl = app.state.rate_limiter
        rl.record_call(capped_before["endpoint_id"], token_count=1000, user_id="test-user-id")

        after = client.get("/dashboard/free-tiers").json()
        capped_after = next(
            r for r in after["rows"] if r["endpoint_id"] == capped_before["endpoint_id"]
        )
    assert capped_after["tpd_used"] == capped_before["tpd_used"] + 1000
    assert capped_after["tpd_remaining"] == capped_before["tpd_remaining"] - 1000


def test_uncapped_provider_excluded_from_headline_not_dropped(client):
    """google's endpoints have no tpd_limit in the registry -- must be listed
    under uncapped_providers, never silently omitted, and must NOT contribute
    an invented number to the headline total (the honest-math rule)."""
    with _keys("google"):
        resp = client.get("/dashboard/free-tiers").json()
    assert "google" in resp["uncapped_providers"]
    assert resp["total_tokens_remaining_today"] is None, (
        "google is this user's only key and has no capped endpoint -- "
        "the headline must be None, not 0 or a guess"
    )
    assert all(r["tpd_remaining"] is None for r in resp["rows"] if r["provider"] == "google")


def test_headline_sums_only_capped_endpoints(client):
    """With both an uncapped (google) and capped (cerebras) provider keyed, the
    headline must equal the sum of capped remaining ONLY."""
    with _keys("google", "cerebras"):
        resp = client.get("/dashboard/free-tiers").json()
    capped_sum = sum(r["tpd_remaining"] for r in resp["rows"] if r["has_published_cap"])
    assert resp["total_tokens_remaining_today"] == capped_sum
    assert "google" in resp["uncapped_providers"]


def test_rows_never_include_a_provider_the_user_holds_no_key_for(client):
    with _keys("groq"):
        resp = client.get("/dashboard/free-tiers").json()
    assert all(r["provider"] == "groq" for r in resp["rows"])


def test_key_source_defaults_to_byok(client):
    """Phase 1b will add a pool key source; until then every row must say so
    explicitly rather than leaving it implicit."""
    with _keys("groq"):
        resp = client.get("/dashboard/free-tiers").json()
    assert resp["rows"] and all(r["key_source"] == "byok" for r in resp["rows"])
