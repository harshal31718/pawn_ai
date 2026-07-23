"""Endpoint quota tracking.

R2 changed three things about the original design:

1. TOKENS ARE ACTUALLY COUNTED. `record_call` used to accept a `token_count`
   argument and discard it, so the `tpm_limit`/`tpd_limit` values already
   present in data/registry/endpoints.json were registered but never enforced.

2. DAY/MONTH WINDOWS PERSIST. All state was in memory, so every backend restart
   silently reset every counter -- a daily limit that resets on restart is not a
   limit. Short windows (rpm/tpm, ~60s) deliberately stay in-memory-only: losing
   them costs at most a minute of backoff accuracy, which isn't worth a database
   write per request. Day/month counters are written behind the request and
   re-seeded at startup.

3. STATE IS KEYED PER USER. PAWN is BYOK: each user calls the provider with
   their OWN key and therefore has their OWN quota. Keying on endpoint_id alone
   meant one user's traffic counted against everyone else's limit, so a busy
   user would prematurely throttle everybody on a multi-user instance.
   `user_id` is optional on every method for backwards compatibility -- calls
   that omit it share the SHARED_USER bucket, which is also where the future
   shared free pool's genuinely-shared quota belongs.
"""
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import time
from typing import Optional

from app.registry.schemas import EndpointEntry
from app.core import usage_store


@dataclass
class _EndpointState:
    # Short rolling windows -- in-memory only, intentionally not persisted.
    rpm_timestamps: deque = field(default_factory=deque)
    tpm_events: deque = field(default_factory=deque)  # (timestamp, tokens)
    # Long windows -- mirrored to Postgres (see usage_store). Calendar-day
    # counters, NOT rolling 24h: providers reset daily quotas at a fixed time,
    # and this must agree with the persisted day window or the two would drift.
    rpd_count: int = 0
    tpd_count: int = 0
    day: date = field(default_factory=lambda: datetime.now(timezone.utc).date())
    # Health.
    cooldown_until: float | None = None
    consecutive_failures: int = 0


class EndpointRateLimiter:
    def __init__(self):
        # Keyed (user_id, endpoint_id). user_id is usage_store.SHARED_USER for
        # unattributed calls.
        self._state: dict[tuple[str, str], _EndpointState] = {}

    # ── internals ────────────────────────────────────────────────────────────

    def _key(self, endpoint_id: str, user_id: Optional[str]) -> tuple[str, str]:
        return (user_id or usage_store.SHARED_USER, endpoint_id)

    def _get(self, endpoint_id: str, user_id: Optional[str] = None) -> _EndpointState:
        key = self._key(endpoint_id, user_id)
        if key not in self._state:
            self._state[key] = _EndpointState()
        return self._state[key]

    def _prune(self, state: _EndpointState) -> None:
        cutoff = time.time() - 60
        while state.rpm_timestamps and state.rpm_timestamps[0] < cutoff:
            state.rpm_timestamps.popleft()
        while state.tpm_events and state.tpm_events[0][0] < cutoff:
            state.tpm_events.popleft()
        # Day rollover. Without this a long-running process would carry
        # yesterday's daily counters forever and lock every endpoint out at the
        # first midnight it survived -- the exact failure the persistence work
        # is meant to prevent, arrived at from the opposite direction.
        today = datetime.now(timezone.utc).date()
        if state.day != today:
            state.day = today
            state.rpd_count = 0
            state.tpd_count = 0

    @staticmethod
    def _tpm_used(state: _EndpointState) -> int:
        return sum(tokens for _, tokens in state.tpm_events)

    # ── startup seeding ──────────────────────────────────────────────────────

    def seed_from_store(self) -> int:
        """Re-load today's persisted day-window counters into memory.

        Called once from app_initializer.initialize_managers(). Without this,
        the process would start believing every daily quota was untouched and
        happily blow straight through limits the user had already consumed.
        Returns the number of buckets seeded (0 if Postgres is unavailable --
        the limiter still works, just without restart survival).
        """
        seeded = 0
        for row in usage_store.load_current("day"):
            state = self._get(row["endpoint_id"], row["user_id"])
            state.rpd_count = int(row.get("requests") or 0)
            state.tpd_count = int(row.get("tokens") or 0)
            seeded += 1
        return seeded

    # ── admission ────────────────────────────────────────────────────────────

    def can_use(self, endpoint: EndpointEntry, user_id: Optional[str] = None) -> bool:
        state = self._get(endpoint.id, user_id)
        self._prune(state)
        now = time.time()
        if state.cooldown_until and now < state.cooldown_until:
            return False
        # Back off at 90% of each published limit rather than 100%: providers
        # count slightly differently than we do, and overshooting means a hard
        # 429 rather than a graceful switch to the next endpoint.
        if endpoint.rpm_limit and len(state.rpm_timestamps) >= 0.9 * endpoint.rpm_limit:
            return False
        if endpoint.rpd_limit and state.rpd_count >= 0.9 * endpoint.rpd_limit:
            return False
        if endpoint.tpm_limit and self._tpm_used(state) >= 0.9 * endpoint.tpm_limit:
            return False
        if endpoint.tpd_limit and state.tpd_count >= 0.9 * endpoint.tpd_limit:
            return False
        return True

    # ── recording ────────────────────────────────────────────────────────────

    def record_call(
        self,
        endpoint_id: str,
        token_count: int = 0,
        user_id: Optional[str] = None,
        persist: bool = True,
    ) -> None:
        """Record one request against an endpoint, plus its token cost.

        `token_count` may legitimately be 0/unknown: several providers ignore
        `stream_options.include_usage`. Unknown is recorded as 0 rather than
        estimated -- an invented number would corrupt the very budget figures
        this exists to make honest. Request counting is unaffected.
        """
        state = self._get(endpoint_id, user_id)
        self._prune(state)
        now = time.time()
        tokens = max(int(token_count or 0), 0)

        state.rpm_timestamps.append(now)
        state.rpd_count += 1
        if tokens:
            state.tpm_events.append((now, tokens))
            state.tpd_count += tokens

        if persist:
            # Write-behind: never blocks the response path beyond one INSERT,
            # and swallows its own failures (see usage_store.record).
            usage_store.record(user_id, endpoint_id, requests=1, tokens=tokens)

    def record_tokens(
        self, endpoint_id: str, token_count: int, user_id: Optional[str] = None
    ) -> None:
        """Attach a token cost to a request already recorded by record_call.

        Needed because streaming reports usage only at the END of the response,
        while the request itself must be recorded at the START (that's what
        makes concurrent calls visible to the rate limiter). Splitting the two
        avoids either double-counting the request or losing the token count.
        """
        tokens = max(int(token_count or 0), 0)
        if not tokens:
            return
        state = self._get(endpoint_id, user_id)
        self._prune(state)
        state.tpm_events.append((time.time(), tokens))
        state.tpd_count += tokens
        usage_store.record(user_id, endpoint_id, requests=0, tokens=tokens)

    def record_429(
        self, endpoint_id: str, retry_after: int = 60, user_id: Optional[str] = None
    ) -> None:
        state = self._get(endpoint_id, user_id)
        state.cooldown_until = time.time() + retry_after
        state.consecutive_failures = 0

    def record_connect_failure(self, endpoint_id: str, user_id: Optional[str] = None) -> None:
        state = self._get(endpoint_id, user_id)
        state.consecutive_failures += 1
        if state.consecutive_failures >= 2:
            state.cooldown_until = time.time() + 20  # dead-host cooldown

    def record_success(self, endpoint_id: str, user_id: Optional[str] = None) -> None:
        self._get(endpoint_id, user_id).consecutive_failures = 0

    def failure_count(self, endpoint_id: str, user_id: Optional[str] = None) -> int:
        """Consecutive failures for one endpoint. Public accessor so callers
        (C3's ranking tiebreak) don't reach into `_state` -- which is keyed
        (user_id, endpoint_id) and easy to index wrongly from outside."""
        key = self._key(endpoint_id, user_id)
        state = self._state.get(key)
        return state.consecutive_failures if state else 0

    # ── reporting ────────────────────────────────────────────────────────────

    def usage_pct(self, endpoint: EndpointEntry, user_id: Optional[str] = None) -> float:
        """Worst-case utilisation across every dimension this endpoint publishes,
        0.0-1.0. Used by C3's headroom tiebreak and the R3 dashboard.

        Max (not mean) because the binding constraint is whichever limit is
        closest to being hit -- an endpoint at 5% of its daily requests but 95%
        of its daily tokens is nearly unusable, and averaging would hide that.
        """
        state = self._get(endpoint.id, user_id)
        self._prune(state)
        pcts = []
        if endpoint.rpm_limit:
            pcts.append(len(state.rpm_timestamps) / endpoint.rpm_limit)
        if endpoint.rpd_limit:
            pcts.append(state.rpd_count / endpoint.rpd_limit)
        if endpoint.tpm_limit:
            pcts.append(self._tpm_used(state) / endpoint.tpm_limit)
        if endpoint.tpd_limit:
            pcts.append(state.tpd_count / endpoint.tpd_limit)
        return max(pcts) if pcts else 0.0

    def snapshot(self, endpoint_id: str, user_id: Optional[str] = None) -> dict:
        """Raw counters for one endpoint (R3 dashboard / debugging)."""
        state = self._get(endpoint_id, user_id)
        self._prune(state)
        return {
            "requests_this_minute": len(state.rpm_timestamps),
            "tokens_this_minute": self._tpm_used(state),
            "requests_today": state.rpd_count,
            "tokens_today": state.tpd_count,
            "cooling_down": bool(state.cooldown_until and time.time() < state.cooldown_until),
        }
