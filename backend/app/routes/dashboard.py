"""R3 + Phase 1b: free-tier budget dashboard.

Aggregates the registry (data/registry/*.json) against real usage from the
rate limiter (R2: token-accurate, per-user, persisted) to answer "how much
free capacity do I actually have left today" -- for a user, not a global
figure, since quota is tracked per-user by construction (true whether the key
behind an endpoint is the user's own BYOK key or the operator's shared pool).

Honest-math rules, deliberately mirrored from OmniRoute's own stated approach
(the inspiration for this dashboard, credited in README.md only): never invent
a number for a provider that publishes no token cap -- list it separately
instead of omitting it or guessing a value that would inflate the headline.

Phase 1b: a row now appears if the user can reach the endpoint through EITHER
key source, and `key_source` reports which one is actually in play for them
right now (see `_usable_key_source`) -- a user with no BYOK keys at all can
still see rows here if the operator has configured pool keys.

PAWN 2.0 Phase A.2 (2026-07-23): `_usable_key_source` is now BYOK-first,
mirroring resolver.Resolver._resolve_key's reversed precedence -- a user
with their own key is reported as "byok" even if the operator has also
configured a pool key for that provider.

PAWN 2.0 Phase D.1 (2026-07-23): pool-sourced rows now report a
`fair_share_remaining` alongside the raw `tpd_remaining` -- the headline's
old math (`tpd_limit - this user's own consumption`) is honest for a BYOK
row (nobody else can touch that key) but overstates a POOL row, since
`tpd_limit` is shared across every registered user, not this user's alone.
`fair_share_remaining` is the conservative, guaranteed-yours floor
(`tpd_limit / N - this user's own consumption`, matching
`core.quota_share`'s fair-share divisor exactly) and is what the headline
total sums for pool rows instead of the raw remaining.
"""
from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import List, Optional

from app.config import read_pool_key
from app.core import key_store, quota_share

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _usable_key_source(ep, user_id: str) -> Optional[str]:
    """Which key source THIS user is actually drawing on for `ep`, or None if
    neither is available. Mirrors resolver.Resolver._resolve_key's precedence
    exactly -- kept as a separate, parallel implementation rather than
    importing the resolver, since this route only needs a yes/no + label, not
    a real key, and doesn't want a dependency on Resolver's constructor
    (registry + rate_limiter) for that.

    **BYOK-first** (PAWN 2.0 Phase A.2, 2026-07-23): reverses Phase 1b's
    pool-first order -- a user with their own key for "either" endpoints is
    reported as "byok", never "pool", even when the operator has also
    configured a pool key for that provider.
    """
    key_source = getattr(ep, "key_source", "byok")
    if key_source != "pool" and key_store.get_key(user_id, ep.provider):
        return "byok"
    if key_source in ("pool", "either") and read_pool_key(ep.provider):
        return "pool"
    return None


class ProviderUsageRow(BaseModel):
    endpoint_id: str
    model_id: str
    display_name: str
    provider: str
    # Phase 1b: reflects which source THIS user is actually drawing on for
    # this endpoint right now ("byok" or "pool"), not a static default --
    # see _usable_key_source above.
    key_source: str = "byok"
    rpd_limit: Optional[int]
    rpd_used: int
    tpd_limit: Optional[int]
    tpd_used: int
    tpd_remaining: Optional[int]  # None when the provider publishes no cap
    has_published_cap: bool
    # PAWN 2.0 Phase D.1: only set for key_source == "pool" -- this user's
    # conservative, guaranteed-yours share of a capped endpoint's daily
    # budget (tpd_limit / N - their own consumption today), matching
    # core.quota_share's fair-share divisor. None for "byok" rows (fair-share
    # doesn't apply -- a BYOK key isn't shared with anyone).
    fair_share_remaining: Optional[int] = None


class FreeTiersResponse(BaseModel):
    # None (not 0) when the user has zero endpoints with a published token cap
    # -- distinguishes "nothing to add up" from "you have exhausted everything",
    # which a bare 0 would conflate.
    total_tokens_remaining_today: Optional[int]
    rows: List[ProviderUsageRow]
    # Providers configured and reachable, but with no published tpd_limit --
    # surfaced separately per the honest-math rule above, never folded into
    # the headline total.
    uncapped_providers: List[str]


@router.get("/free-tiers", response_model=FreeTiersResponse)
async def get_free_tiers(request: Request) -> FreeTiersResponse:
    """This user's free-tier budget: every model+provider endpoint they hold a
    key for, with today's usage and remaining token headroom.

    Deliberately per-user, not global -- PAWN is BYOK, so "free tokens
    available" only means something relative to whichever keys THIS user has
    configured. A user with no keys gets an empty response, not an error: an
    empty dashboard is the correct state for "you haven't added any keys yet",
    mirroring how Resolver.pick() itself treats a keyless user.
    """
    user_id = request.state.user_id
    registry = request.app.state.registry
    rate_limiter = request.app.state.rate_limiter

    rows: List[ProviderUsageRow] = []
    uncapped_providers: set[str] = set()
    total_remaining = 0
    any_capped = False

    for model in registry.user_models():
        for ep in registry.endpoints_for(model.id):
            key_source = _usable_key_source(ep, user_id)
            if key_source is None:
                continue  # neither BYOK nor pool key usable here -- not this user's to see

            snapshot = rate_limiter.snapshot(ep.id, user_id=user_id)
            has_cap = ep.tpd_limit is not None
            remaining = max(ep.tpd_limit - snapshot["tokens_today"], 0) if has_cap else None

            # PAWN 2.0 Phase D.1: pool-dedupe headline -- a pool row's raw
            # `remaining` overstates what's actually this user's, since
            # `tpd_limit` is shared. Fall open to the raw `remaining` on any
            # quota_share error (fail-open, same posture as quota_share
            # itself) rather than hiding the row.
            fair_share_remaining = None
            headline_contribution = remaining
            if has_cap and key_source == "pool":
                try:
                    n = quota_share.registered_user_count()
                    fair_share_remaining = max(int(ep.tpd_limit / n) - snapshot["tokens_today"], 0)
                    headline_contribution = fair_share_remaining
                except Exception:
                    pass

            if has_cap:
                any_capped = True
                total_remaining += headline_contribution
            else:
                uncapped_providers.add(ep.provider)

            rows.append(
                ProviderUsageRow(
                    endpoint_id=ep.id,
                    model_id=model.id,
                    display_name=model.display_name,
                    provider=ep.provider,
                    key_source=key_source,
                    fair_share_remaining=fair_share_remaining,
                    rpd_limit=ep.rpd_limit,
                    rpd_used=snapshot["requests_today"],
                    tpd_limit=ep.tpd_limit,
                    tpd_used=snapshot["tokens_today"],
                    tpd_remaining=remaining,
                    has_published_cap=has_cap,
                )
            )

    return FreeTiersResponse(
        total_tokens_remaining_today=total_remaining if any_capped else None,
        rows=rows,
        uncapped_providers=sorted(uncapped_providers),
    )
