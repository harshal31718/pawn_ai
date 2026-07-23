"""PAWN 2.0 Phase C: shared-pool fair-share quota.

Faithful port of OmniRoute's quota-share engine (`enforce.ts`/`fairShare.ts`)
into PAWN's much simpler shape -- see
`workspace/plan/architecture_2.0/01_quota_share_port.md` for the full mapping
and the reasoning behind every simplification. Applies ONLY to pool-sourced
calls (`resolver.pick()`'s `key_source == "pool"`); BYOK users keep today's
existing per-user-vs-full-limit accounting, completely untouched by this
module.

Fail-open throughout (matches every other quota-accounting path in this
codebase, e.g. usage_store's persistence circuit-breaker): any DB/config
error here means "allow", never "block" -- a quota_share bug must not be
able to take down the whole pool.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from typing import Optional

from app.core import pool_key_store, usage_store
from app.db.postgres_client import fetchone

DEFAULT_SATURATION_PCT = 80

# C.1: registered-user count N, lazily recomputed once per UTC day (not on
# every call -- a scheduler dependency isn't worth it for a number that only
# needs to be roughly current). `N = max(N, 1)` so a fresh/empty deployment
# never divides by zero. Counted from the MAIN app DB (POSTGRES_DSN, via the
# default `fetchone` -- this deliberately does NOT go through
# key_store/pool_key_store's SHARED_DB_DSN wrappers), since N is "how many
# users this deployment serves", not a property of the shared keys DB.
_cached_n: Optional[int] = None
_cached_day: Optional[date] = None


def _today() -> date:
    return datetime.now(timezone.utc).date()


def registered_user_count() -> int:
    """N -- see module docstring. Fails open to the last known value (or 1)
    on any DB error, so a transient Postgres hiccup degrades to the most
    recent good count rather than a divide-by-zero or an unbounded pool."""
    global _cached_n, _cached_day
    today = _today()
    if _cached_day == today and _cached_n is not None:
        return _cached_n
    try:
        row = fetchone("select count(*) as n from users")
        n = max(int(row["n"]) if row else 1, 1)
    except Exception as e:  # noqa: BLE001
        print(f"quota_share: registered_user_count failed (non-fatal): {e}", file=sys.stderr)
        n = _cached_n if _cached_n is not None else 1
    _cached_n, _cached_day = n, today
    return n


def reset_cache() -> None:
    """Test hook / manual recompute trigger (e.g. after seeding fake `users`
    rows to exercise N > 1 in an otherwise-solo-dev environment)."""
    global _cached_n, _cached_day
    _cached_n, _cached_day = None, None


def enforce(ep, user_id: Optional[str], rate_limiter) -> bool:
    """PRE-request gate for a pool-sourced call. Returns True (allow) or
    False (block -- caller should treat the endpoint as exhausted and let
    the existing `fallback_models` failover proceed, per Phase C.4).

    Only ever called for `key_source == "pool"` endpoints (see
    `Resolver.pick`) -- this does not duplicate `rate_limiter.can_use`'s
    existing check against the endpoint's real published limit; it layers
    the per-user fair-share limit ON TOP of that.

    `rate_limiter` is accepted (not imported) so tests can inject a fake
    without needing a real EndpointRateLimiter -- it's currently unused
    (headroom is derived from `usage_store`, not the in-memory limiter) but
    kept in the signature since C.4's call site already has it in scope and
    a future dimension (rpm/tpm burst awareness) may want it.
    """
    try:
        return _enforce(ep, user_id)
    except Exception as e:  # noqa: BLE001
        print(f"quota_share: enforce failed (non-fatal, allowing): {e}", file=sys.stderr)
        return True


def _enforce(ep, user_id: Optional[str]) -> bool:
    config = pool_key_store.get_pool_config(ep.provider)
    saturation_pct = DEFAULT_SATURATION_PCT
    if config is not None and config.get("saturation_pct") is not None:
        saturation_pct = config["saturation_pct"]

    n = registered_user_count()

    for limit_attr, unit_key in (("tpd_limit", "tokens"), ("rpd_limit", "requests")):
        pool_limit = getattr(ep, limit_attr)
        if not pool_limit:
            continue  # no published cap for this dimension -- nothing to share

        shared_row = usage_store.usage_for_endpoint(usage_store.SHARED_USER, ep.id)
        own_row = usage_store.usage_for_endpoint(user_id, ep.id)
        shared_total = shared_row[unit_key]
        own_consumed = own_row[unit_key]

        fair_share = pool_limit / n

        # Absolute pool cap -- checked BEFORE the generous/strict branch and
        # regardless of this caller's own (possibly-zero) consumption. Ported
        # from OmniRoute's `dim.consumedTotal >= dim.limit` check in
        # decideFairShare: without it, a brand-new user with zero consumption
        # of their own would always pass the strict-mode fair-share check
        # even when the shared pool has already hit its real published
        # rpd/tpd limit -- fair-share math must never override the absolute
        # ceiling it's supposed to divide UP, not around.
        if shared_total >= pool_limit:
            return False

        is_strict = (shared_total / pool_limit) >= (saturation_pct / 100)

        if not is_strict:
            # Generous / work-conserving: headroom already confirmed above --
            # allow regardless of this caller's own share so far.
            pass
        else:
            # Strict: confine to this user's fair share. `soft`/`burst`
            # policies are ported for fidelity (see decideFairShare in the
            # OmniRoute source) but PAWN ships `hard` as the only active
            # policy today -- no per-endpoint policy field exists yet.
            if own_consumed >= fair_share:
                return False

    return True
