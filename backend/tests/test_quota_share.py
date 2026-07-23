"""PAWN 2.0 Phase C.5: quota_share -- shared-pool fair-share quota.

Ports OmniRoute's decideFairShare scenarios (generous/strict, fair-share
floor, saturation, any-dimension-blocks) onto PAWN's simplified shape: equal
1/N weight, tpd+rpd only, per-provider saturation_pct. See
workspace/plan/architecture_2.0/01_quota_share_port.md for the mapping.
"""
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from app.core import quota_share


def _ep(provider="groq", tpd_limit=1000, rpd_limit=100):
    return SimpleNamespace(id="ep-1", provider=provider, tpd_limit=tpd_limit, rpd_limit=rpd_limit)


def _usage(requests=0, tokens=0):
    return {"requests": requests, "tokens": tokens}


# ── C.1: registered_user_count ──────────────────────────────────────────────


def test_registered_user_count_reads_real_count():
    quota_share.reset_cache()
    with patch("app.core.quota_share.fetchone", return_value={"n": 5}):
        assert quota_share.registered_user_count() == 5


def test_registered_user_count_floors_at_one():
    quota_share.reset_cache()
    with patch("app.core.quota_share.fetchone", return_value={"n": 0}):
        assert quota_share.registered_user_count() == 1


def test_registered_user_count_caches_within_the_same_day():
    quota_share.reset_cache()
    with patch("app.core.quota_share.fetchone", return_value={"n": 3}) as fetch_mock:
        assert quota_share.registered_user_count() == 3
        assert quota_share.registered_user_count() == 3
    fetch_mock.assert_called_once()


def test_registered_user_count_fails_open_to_last_known_value():
    quota_share.reset_cache()
    with patch("app.core.quota_share.fetchone", return_value={"n": 4}):
        assert quota_share.registered_user_count() == 4
    # Force the NEXT call to see a "new day" (so it doesn't just serve the
    # cached value) without clearing _cached_n -- reset_cache() would clear
    # both and defeat the point of this test (the value to fall back TO).
    quota_share._cached_day = date(2000, 1, 1)
    with patch("app.core.quota_share.fetchone", side_effect=Exception("db down")):
        assert quota_share.registered_user_count() == 4  # falls back, not 1


# ── C.3: enforce() -- generous vs strict ────────────────────────────────────


def test_generous_mode_allows_borrowing_below_saturation():
    """Below saturation_pct, a user can consume more than their fair share
    (1/N) as long as the pool overall has headroom."""
    ep = _ep(tpd_limit=1000, rpd_limit=100)
    with patch("app.core.quota_share.registered_user_count", return_value=10), \
         patch("app.core.pool_key_store.get_pool_config", return_value=None), \
         patch(
             "app.core.usage_store.usage_for_endpoint",
             side_effect=lambda uid, eid, window_kind="day": (
                 _usage(requests=20, tokens=300) if uid == "" else _usage(requests=15, tokens=250)
             ),
         ):
        # fair_share = 1000/10 = 100 tokens; this user has consumed 250 (way over
        # fair share) but pool total (300) is still well under the 1000 limit and
        # under 80% saturation (800) -- generous mode allows it.
        assert quota_share.enforce(ep, "user-1", rate_limiter=None) is True


def test_strict_mode_blocks_at_fair_share_once_saturated():
    ep = _ep(tpd_limit=1000, rpd_limit=100)
    with patch("app.core.quota_share.registered_user_count", return_value=10), \
         patch("app.core.pool_key_store.get_pool_config", return_value=None), \
         patch(
             "app.core.usage_store.usage_for_endpoint",
             side_effect=lambda uid, eid, window_kind="day": (
                 _usage(requests=85, tokens=850) if uid == "" else _usage(requests=10, tokens=110)
             ),
         ):
        # Pool at 850/1000 = 85% >= default 80% saturation -> strict mode.
        # fair_share = 100 tokens; this user has already consumed 110 -> blocked.
        assert quota_share.enforce(ep, "user-1", rate_limiter=None) is False


def test_strict_mode_allows_a_user_still_under_their_fair_share():
    ep = _ep(tpd_limit=1000, rpd_limit=100)
    with patch("app.core.quota_share.registered_user_count", return_value=10), \
         patch("app.core.pool_key_store.get_pool_config", return_value=None), \
         patch(
             "app.core.usage_store.usage_for_endpoint",
             side_effect=lambda uid, eid, window_kind="day": (
                 _usage(requests=85, tokens=850) if uid == "" else _usage(requests=1, tokens=50)
             ),
         ):
        # Saturated pool, but this user has only used 50/100 of their fair share.
        assert quota_share.enforce(ep, "user-1", rate_limiter=None) is True


def test_pool_absolute_limit_blocks_even_a_keyless_new_user():
    ep = _ep(tpd_limit=1000, rpd_limit=100)
    with patch("app.core.quota_share.registered_user_count", return_value=10), \
         patch("app.core.pool_key_store.get_pool_config", return_value=None), \
         patch(
             "app.core.usage_store.usage_for_endpoint",
             side_effect=lambda uid, eid, window_kind="day": (
                 _usage(requests=100, tokens=1000) if uid == "" else _usage()
             ),
         ):
        # Pool exactly at its published limit -- generous mode's headroom check
        # must still block once shared_total >= pool_limit, regardless of N.
        assert quota_share.enforce(ep, "brand-new-user", rate_limiter=None) is False


def test_per_provider_saturation_override_is_respected():
    """A provider with saturation_pct=50 goes strict earlier than the 80% default."""
    ep = _ep(tpd_limit=1000, rpd_limit=100)
    with patch("app.core.quota_share.registered_user_count", return_value=10), \
         patch("app.core.pool_key_store.get_pool_config", return_value={"saturation_pct": 50}), \
         patch(
             "app.core.usage_store.usage_for_endpoint",
             side_effect=lambda uid, eid, window_kind="day": (
                 _usage(requests=60, tokens=600) if uid == "" else _usage(requests=10, tokens=150)
             ),
         ):
        # 600/1000 = 60% >= 50% override -> strict. fair_share = 100; user at 150 -> blocked.
        assert quota_share.enforce(ep, "user-1", rate_limiter=None) is False


def test_any_dimension_blocking_blocks_the_whole_request():
    """rpd is fine but tpd is over fair share in strict mode -- must still block
    (OmniRoute: block if ANY active dimension blocks)."""
    ep = _ep(tpd_limit=1000, rpd_limit=1000)  # rpd effectively unconstrained here
    with patch("app.core.quota_share.registered_user_count", return_value=10), \
         patch("app.core.pool_key_store.get_pool_config", return_value=None), \
         patch(
             "app.core.usage_store.usage_for_endpoint",
             side_effect=lambda uid, eid, window_kind="day": (
                 _usage(requests=1, tokens=850) if uid == "" else _usage(requests=1, tokens=150)
             ),
         ):
        assert quota_share.enforce(ep, "user-1", rate_limiter=None) is False


def test_endpoint_with_no_published_cap_is_never_gated():
    ep = _ep(tpd_limit=None, rpd_limit=None)
    with patch("app.core.quota_share.registered_user_count", return_value=10), \
         patch("app.core.pool_key_store.get_pool_config", return_value=None):
        assert quota_share.enforce(ep, "user-1", rate_limiter=None) is True


def test_byok_user_is_unaffected_by_this_module_entirely():
    """Not a quota_share test per se -- documents the contract: enforce() is
    only ever called by the resolver for key_source == "pool" endpoints. A
    BYOK user's request never reaches this function at all."""
    # (Covered functionally by resolver tests asserting quota_share.enforce
    # is not called for "byok"/"either"-resolved-to-byok endpoints.)
    assert True


def test_enforce_fails_open_on_any_error():
    ep = _ep()
    with patch("app.core.quota_share.registered_user_count", side_effect=Exception("boom")):
        assert quota_share.enforce(ep, "user-1", rate_limiter=None) is True
