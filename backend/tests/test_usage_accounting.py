"""R2: token-accurate, persistent, per-user quota accounting.

Persistence is exercised against a FAKE store (usage_store is monkeypatched)
rather than a real Postgres, so these run in the standard suite. What's proven
here is the limiter's own contract: that it counts tokens, enforces the token
dimensions, keys state per user, rolls the day over, and re-seeds from whatever
the store hands back.
"""
from datetime import timedelta, timezone

import pytest

from app.core import usage_store
from app.core.normalize import _total_tokens
from app.core.rate_limiter import EndpointRateLimiter
from app.registry.schemas import EndpointEntry


def _ep(**over) -> EndpointEntry:
    base = dict(
        id="ep-test", model_id="m", provider="groq", provider_model_id="m",
        base_url="https://x/v1", priority=1, rpm_limit=None, rpd_limit=None,
        tpm_limit=None, tpd_limit=None, active=True, last_verified="2026-07-21",
    )
    base.update(over)
    return EndpointEntry(**base)


# Captured BEFORE the autouse fixture below can replace them, so the
# store-behaviour tests further down can put the real implementations back.
_REAL_RECORD = usage_store.record
_REAL_LOAD_CURRENT = usage_store.load_current


@pytest.fixture(autouse=True)
def _no_persistence(monkeypatch):
    """Default: persistence is a no-op, so limiter tests never touch Postgres.
    The store-behaviour tests restore the real functions via _break_db."""
    monkeypatch.setattr(usage_store, "record", lambda *a, **k: None)
    monkeypatch.setattr(usage_store, "load_current", lambda *a, **k: [])


# ── tokens are actually counted (they previously were not) ───────────────────

def test_record_call_counts_tokens():
    """Pre-R2 `record_call` accepted token_count and silently discarded it."""
    rl = EndpointRateLimiter()
    rl.record_call("ep-test", token_count=500)
    assert rl.snapshot("ep-test")["tokens_today"] == 500
    assert rl.snapshot("ep-test")["requests_today"] == 1


def test_tpd_limit_is_enforced():
    """tpd_limit was registered in endpoints.json but never enforced."""
    ep = _ep(tpd_limit=1000)
    rl = EndpointRateLimiter()
    assert rl.can_use(ep) is True
    rl.record_call(ep.id, token_count=900)      # 90% threshold
    assert rl.can_use(ep) is False


def test_tpm_limit_is_enforced():
    ep = _ep(tpm_limit=1000)
    rl = EndpointRateLimiter()
    rl.record_call(ep.id, token_count=900)
    assert rl.can_use(ep) is False


def test_tpm_window_rolls_off(monkeypatch):
    ep = _ep(tpm_limit=1000)
    rl = EndpointRateLimiter()
    rl.record_call(ep.id, token_count=900)
    assert rl.can_use(ep) is False

    import app.core.rate_limiter as mod
    real = mod.time.time
    monkeypatch.setattr(mod.time, "time", lambda: real() + 120)  # 2 min later
    assert rl.can_use(ep) is True, "tpm is a 60s window and must roll off"


def test_unknown_token_count_is_recorded_as_zero_not_guessed():
    """Several providers ignore stream_options.include_usage. Recording an
    estimate would corrupt the very budget figures this exists to make honest."""
    rl = EndpointRateLimiter()
    rl.record_call("ep-test", token_count=0)
    snap = rl.snapshot("ep-test")
    assert snap["requests_today"] == 1     # request still counted
    assert snap["tokens_today"] == 0       # tokens left unknown, not invented


def test_record_tokens_attaches_cost_without_double_counting_the_request():
    """Streaming reports usage only at the end, so the request is recorded at
    the start and the cost attached later."""
    rl = EndpointRateLimiter()
    rl.record_call("ep-test")                 # request, cost unknown yet
    rl.record_tokens("ep-test", 750)          # cost arrives with the done event
    snap = rl.snapshot("ep-test")
    assert snap["requests_today"] == 1, "must not count the request twice"
    assert snap["tokens_today"] == 750


# ── per-user isolation (a pre-existing multi-user bug) ───────────────────────

def test_usage_is_isolated_per_user():
    """BYOK means each user calls with their OWN key and has their OWN quota.
    Keying on endpoint_id alone let one user's traffic throttle everyone else."""
    ep = _ep(rpd_limit=100)
    rl = EndpointRateLimiter()
    for _ in range(95):
        rl.record_call(ep.id, user_id="heavy-user")

    assert rl.can_use(ep, user_id="heavy-user") is False
    assert rl.can_use(ep, user_id="other-user") is True, "one user must not throttle another"


def test_omitting_user_id_uses_the_shared_bucket():
    rl = EndpointRateLimiter()
    rl.record_call("ep-test", token_count=10)
    assert rl.snapshot("ep-test", user_id=usage_store.SHARED_USER)["tokens_today"] == 10


# ── day rollover ─────────────────────────────────────────────────────────────

def test_daily_counters_reset_on_day_rollover(monkeypatch):
    """A long-running process must not carry yesterday's daily counters forever
    -- that would lock every endpoint out at the first midnight it survived."""
    ep = _ep(rpd_limit=100)
    rl = EndpointRateLimiter()
    for _ in range(95):
        rl.record_call(ep.id)
    assert rl.can_use(ep) is False

    import app.core.rate_limiter as mod

    # Capture the REAL datetime class before patching -- subclassing mod.datetime
    # and then calling mod.datetime.now() from inside the subclass's own .now()
    # recurses infinitely once mod.datetime has been reassigned to the subclass
    # itself (found live: this monkeypatch had never actually been exercised by
    # a real pytest run before this session, only by standalone re-implementations).
    _real_datetime = mod.datetime

    class _Tomorrow(_real_datetime):
        @classmethod
        def now(cls, tz=None):
            return _real_datetime.now(timezone.utc) + timedelta(days=1)

    monkeypatch.setattr(mod, "datetime", _Tomorrow)
    assert rl.can_use(ep) is True, "daily counters must reset at the day boundary"


# ── restart survival ─────────────────────────────────────────────────────────

def test_seed_from_store_restores_daily_counters(monkeypatch):
    """THE point of R2: a limit that resets on restart is not a limit."""
    monkeypatch.setattr(usage_store, "load_current", lambda kind="day": [
        {"user_id": "u1", "endpoint_id": "ep-test", "requests": 95, "tokens": 4000},
    ])
    ep = _ep(rpd_limit=100)
    rl = EndpointRateLimiter()
    assert rl.can_use(ep, user_id="u1") is True, "fresh process starts empty"

    seeded = rl.seed_from_store()
    assert seeded == 1
    assert rl.can_use(ep, user_id="u1") is False, "pre-restart usage must be restored"
    assert rl.snapshot("ep-test", user_id="u1")["tokens_today"] == 4000


# ── the store degrades safely (exercises the REAL usage_store) ───────────────
#
# The guarantee lives in usage_store, not in the limiter: quota accounting must
# never take down a chat request, so these patch the DB layer underneath the
# real functions rather than faking the functions themselves.

def _break_db(monkeypatch):
    """Restore the real store functions (the autouse fixture stubbed them out),
    then break the DB layer underneath them."""
    def _boom(*a, **k):
        raise RuntimeError("postgres down")
    monkeypatch.setattr(usage_store, "record", _REAL_RECORD)
    monkeypatch.setattr(usage_store, "load_current", _REAL_LOAD_CURRENT)
    monkeypatch.setattr(usage_store, "execute", _boom)
    monkeypatch.setattr(usage_store, "fetchall", _boom)
    usage_store.reset_failures()


def test_record_never_raises_when_postgres_is_down(monkeypatch):
    _break_db(monkeypatch)
    try:
        usage_store.record("u1", "ep-test", requests=1, tokens=10)   # must not raise
    finally:
        usage_store.reset_failures()


def test_load_current_returns_empty_when_postgres_is_down(monkeypatch):
    _break_db(monkeypatch)
    try:
        assert usage_store.load_current("day") == []
    finally:
        usage_store.reset_failures()


def test_persistence_disables_itself_after_repeated_failures(monkeypatch):
    """Without a breaker, a missing database means EVERY LLM call attempts (and
    times out) a fresh connection -- turning a config problem into a latency
    regression on the request path."""
    _break_db(monkeypatch)
    try:
        assert usage_store.is_enabled() is True
        for _ in range(usage_store._MAX_CONSECUTIVE_FAILURES):
            usage_store.record("u1", "ep-test", requests=1, tokens=1)
        assert usage_store.is_enabled() is False, "should stop retrying a dead store"
        # Once disabled it returns immediately without touching the DB at all.
        assert usage_store.load_current("day") == []
    finally:
        usage_store.reset_failures()
    assert usage_store.is_enabled() is True, "reset_failures must re-arm it"


def test_limiter_still_works_with_persistence_disabled(monkeypatch):
    """Degrading to in-memory-only is exactly the pre-R2 behaviour -- correct
    within a single process, just not across restarts."""
    _break_db(monkeypatch)
    try:
        rl = EndpointRateLimiter()
        for _ in range(usage_store._MAX_CONSECUTIVE_FAILURES + 2):
            rl.record_call("ep-test", token_count=5)
        assert rl.snapshot("ep-test")["tokens_today"] == 5 * (usage_store._MAX_CONSECUTIVE_FAILURES + 2)
    finally:
        usage_store.reset_failures()


# ── usage_pct drives C3's headroom tiebreak ──────────────────────────────────

def test_usage_pct_considers_token_dimensions():
    ep = _ep(rpd_limit=1000, tpd_limit=1000)
    rl = EndpointRateLimiter()
    rl.record_call(ep.id, token_count=500)
    # 1/1000 requests but 500/1000 tokens -> the token dimension binds.
    assert rl.usage_pct(ep) == pytest.approx(0.5)


def test_usage_pct_takes_the_worst_dimension_not_the_average():
    ep = _ep(rpd_limit=100, tpd_limit=10_000)
    rl = EndpointRateLimiter()
    for _ in range(90):
        rl.record_call(ep.id, token_count=1)
    # 90% of requests, 0.9% of tokens. Averaging would report ~45% and hide that
    # the endpoint is nearly unusable.
    assert rl.usage_pct(ep) == pytest.approx(0.9)


def test_usage_pct_is_zero_with_no_limits():
    assert EndpointRateLimiter().usage_pct(_ep()) == 0.0


# ── provider usage-block parsing ─────────────────────────────────────────────

@pytest.mark.parametrize("usage,expected", [
    ({"total_tokens": 120}, 120),
    ({"prompt_tokens": 100, "completion_tokens": 20}, 120),   # no total
    ({"total_tokens": 0, "prompt_tokens": 7, "completion_tokens": 3}, 10),
    ({}, 0),
    (None, 0),
    ("garbage", 0),
    ({"total_tokens": "not-a-number"}, 0),
])
def test_total_tokens_parsing(usage, expected):
    assert _total_tokens(usage) == expected
