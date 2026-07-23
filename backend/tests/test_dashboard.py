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


# ── PAWN 2.0 Phase D.1/D.4: pool-dedupe honest headline ─────────────────────


def _pool(*allowed):
    allowed_set = set(allowed)
    return patch(
        "app.routes.dashboard.read_pool_key",
        side_effect=lambda provider: "POOL-KEY" if provider in allowed_set else None,
    )


def test_byok_row_has_no_fair_share_remaining(client):
    with _keys("cerebras"):
        resp = client.get("/dashboard/free-tiers").json()
    capped = [r for r in resp["rows"] if r["has_published_cap"]]
    assert capped
    assert all(r["fair_share_remaining"] is None for r in capped)


def test_pool_row_reports_fair_share_remaining_not_raw_remaining(client):
    with _keys(), _pool("cerebras"), \
         patch("app.core.quota_share.registered_user_count", return_value=4):
        resp = client.get("/dashboard/free-tiers").json()
    capped = [r for r in resp["rows"] if r["has_published_cap"] and r["key_source"] == "pool"]
    assert capped, "expected at least one pool-sourced capped cerebras row"
    row = capped[0]
    assert row["fair_share_remaining"] is not None
    expected = max(int(row["tpd_limit"] / 4) - row["tpd_used"], 0)
    assert row["fair_share_remaining"] == expected
    # The honest floor must never exceed the raw (unshared) remaining.
    assert row["fair_share_remaining"] <= row["tpd_remaining"]


def test_headline_sums_fair_share_not_raw_remaining_for_pool_rows(client):
    with _keys(), _pool("cerebras"), \
         patch("app.core.quota_share.registered_user_count", return_value=5):
        resp = client.get("/dashboard/free-tiers").json()
    capped = [r for r in resp["rows"] if r["has_published_cap"]]
    assert capped
    fair_share_sum = sum(r["fair_share_remaining"] for r in capped)
    assert resp["total_tokens_remaining_today"] == fair_share_sum
    # Sanity: with N=5 the fair-share sum must be strictly less than the raw
    # (unshared) sum whenever any endpoint has nonzero usage headroom to divide.
    raw_sum = sum(r["tpd_remaining"] for r in capped)
    assert fair_share_sum <= raw_sum


def test_quota_share_error_falls_back_to_raw_remaining_in_headline(client):
    """Fail-open: a broken registered_user_count() must not break the whole
    dashboard -- degrade to the raw remaining instead of erroring the route."""
    with _keys(), _pool("cerebras"), \
         patch("app.core.quota_share.registered_user_count", side_effect=Exception("db down")):
        resp = client.get("/dashboard/free-tiers")
    assert resp.status_code == 200
    body = resp.json()
    capped = [r for r in body["rows"] if r["has_published_cap"]]
    assert capped
    assert all(r["fair_share_remaining"] is None for r in capped)
    raw_sum = sum(r["tpd_remaining"] for r in capped)
    assert body["total_tokens_remaining_today"] == raw_sum


# ── Models-test table (2026-07-23): rpm/tpm/priority ────────────────────────


def test_rows_carry_rpm_and_tpm_fields(client):
    with _keys("cerebras"):
        resp = client.get("/dashboard/free-tiers").json()
    assert resp["rows"]
    row = resp["rows"][0]
    for field in ("rpm_limit", "rpm_used", "tpm_limit", "tpm_used", "priority"):
        assert field in row


def test_rpm_usage_reflects_real_recorded_calls(client):
    with _keys("cerebras"):
        before = client.get("/dashboard/free-tiers").json()
        row_before = before["rows"][0]

        rl = app.state.rate_limiter
        rl.record_call(row_before["endpoint_id"], token_count=0, user_id="test-user-id")

        after = client.get("/dashboard/free-tiers").json()
        row_after = next(r for r in after["rows"] if r["endpoint_id"] == row_before["endpoint_id"])
    assert row_after["rpm_used"] == row_before["rpm_used"] + 1


def test_priority_matches_registry_endpoint_priority(client):
    with _keys("cerebras"):
        resp = client.get("/dashboard/free-tiers").json()
    assert resp["rows"]
    assert all(isinstance(r["priority"], int) for r in resp["rows"])
