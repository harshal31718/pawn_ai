"""R2: Postgres-backed persistence for endpoint quota accounting.

Split out of rate_limiter.py so the limiter stays a pure in-memory hot-path
structure with no database import, and so tests can exercise the limiter
without Postgres (every function here is exception-safe and degrades to a
no-op / empty result, matching key_store.py's established posture).

Only DAY and MONTH windows are persisted. The rpm/tpm windows are ~60s wide, so
losing them on restart costs at most a minute of backoff accuracy -- not worth a
database write per request.

Grain is (user_id, endpoint_id, window_kind, window_start); see the migration
2026-07_R2_endpoint_usage.sql for why user_id is part of the key.
"""
from __future__ import annotations

import sys
from datetime import date, timezone, datetime

from app.db.postgres_client import execute, fetchall

# Sentinel for usage that isn't attributable to a specific user (internal calls
# with no user_id, and later the shared free pool whose quota really is shared).
# Empty string rather than NULL so it participates in the primary key.
SHARED_USER = ""

# Persistence circuit-breaker. If Postgres is absent or misconfigured, every
# record() would otherwise attempt (and time out) a fresh connection on EVERY
# LLM call -- turning a missing database into a severe latency regression on the
# request path, and making the test suite crawl. After this many consecutive
# failures we stop trying and degrade to in-memory-only accounting, which is
# exactly the pre-R2 behaviour. reset_failures() re-arms it (used by tests, and
# available if a deployment repairs its database without a restart).
_MAX_CONSECUTIVE_FAILURES = 3
_consecutive_failures = 0
_disabled = False


def reset_failures() -> None:
    """Re-arm persistence after it was disabled by repeated failures."""
    global _consecutive_failures, _disabled
    _consecutive_failures = 0
    _disabled = False


def is_enabled() -> bool:
    return not _disabled


def _note_failure(where: str, err: Exception) -> None:
    global _consecutive_failures, _disabled
    _consecutive_failures += 1
    if _consecutive_failures >= _MAX_CONSECUTIVE_FAILURES and not _disabled:
        _disabled = True
        print(
            f"usage_store: disabling persistence after {_consecutive_failures} "
            f"consecutive failures; quota accounting is now in-memory only "
            f"(last error in {where}: {err})",
            file=sys.stderr,
        )
    elif not _disabled:
        print(f"usage_store.{where} failed (non-fatal): {err}", file=sys.stderr)


def _note_success() -> None:
    global _consecutive_failures
    _consecutive_failures = 0


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _month_start(d: date | None = None) -> date:
    d = d or _today()
    return d.replace(day=1)


def current_windows() -> list[tuple[str, date]]:
    """The (window_kind, window_start) pairs that 'now' falls into."""
    return [("day", _today()), ("month", _month_start())]


def record(user_id: str | None, endpoint_id: str, requests: int, tokens: int) -> None:
    """Add `requests`/`tokens` to every current window for this endpoint.

    Best-effort and exception-safe: quota accounting must never take down a
    chat request. A dropped write under-counts usage, which is the safe
    direction (we allow slightly more than the limit rather than wrongly
    locking a user out).
    """
    if (requests <= 0 and tokens <= 0) or _disabled:
        return
    uid = user_id or SHARED_USER
    try:
        for kind, start in current_windows():
            execute(
                """
                insert into endpoint_usage
                    (user_id, endpoint_id, window_kind, window_start, requests, tokens)
                values (%s, %s, %s, %s, %s, %s)
                on conflict (user_id, endpoint_id, window_kind, window_start)
                do update set
                    requests   = endpoint_usage.requests + excluded.requests,
                    tokens     = endpoint_usage.tokens + excluded.tokens,
                    updated_at = now()
                """,
                (uid, endpoint_id, kind, start, max(requests, 0), max(tokens, 0)),
            )
        _note_success()
    except Exception as e:  # noqa: BLE001 - see docstring
        _note_failure("record", e)


def load_current(window_kind: str = "day") -> list[dict]:
    """All usage rows for the current window. Used to seed the in-memory limiter
    at startup and by the R3 dashboard. Returns [] if Postgres is unavailable."""
    if _disabled:
        return []
    start = _today() if window_kind == "day" else _month_start()
    try:
        rows = fetchall(
            """
            select user_id, endpoint_id, requests, tokens
            from endpoint_usage
            where window_kind = %s and window_start = %s
            """,
            (window_kind, start),
        )
        _note_success()
        return rows
    except Exception as e:  # noqa: BLE001
        _note_failure("load_current", e)
        return []


def usage_for_user(user_id: str | None, window_kind: str = "day") -> list[dict]:
    """This user's usage rows for the current window (R3 dashboard)."""
    if _disabled:
        return []
    uid = user_id or SHARED_USER
    start = _today() if window_kind == "day" else _month_start()
    try:
        rows = fetchall(
            """
            select endpoint_id, requests, tokens
            from endpoint_usage
            where user_id = %s and window_kind = %s and window_start = %s
            """,
            (uid, window_kind, start),
        )
        _note_success()
        return rows
    except Exception as e:  # noqa: BLE001
        _note_failure("usage_for_user", e)
        return []
