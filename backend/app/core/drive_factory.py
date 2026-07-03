"""Factory for creating per-user DriveStorage instances.

Fetches encrypted Drive tokens from Postgres, decrypts them,
and returns a ready-to-use DriveStorage object.

Usage in a FastAPI route:
    from app.core.drive_factory import get_drive_for_user
    drive = get_drive_for_user(request.state.user_id)
"""

import threading
import time
from typing import Optional

from app.core.crypto import decrypt
from app.db.postgres_client import execute, fetchone
from app.storage.drive import DriveStorage

# Cache DriveStorage instances per user so we don't refetch tokens from Postgres
# and rebuild the Drive service (plus its folder/file-ID caches) on every request.
# The instance refreshes its own OAuth token in place, so it stays valid for its
# whole lifetime; we still bound it with a TTL so a re-link is eventually picked up
# (and evict_user() forces it immediately).
_CACHE: dict[str, tuple[float, Optional[DriveStorage]]] = {}
_CACHE_LOCK = threading.Lock()
_TTL_OK = 600.0   # cache a live DriveStorage for 10 minutes
_TTL_NONE = 30.0  # cache a "not linked / unavailable" result briefly to avoid hammering Postgres


def evict_user(user_id: str) -> None:
    """Drop any cached DriveStorage for a user (e.g. after they (re)link Drive)."""
    with _CACHE_LOCK:
        _CACHE.pop(user_id, None)


def get_drive_for_user(user_id: str) -> Optional[DriveStorage]:
    """
    Return a (cached) DriveStorage for the user, or None if Drive is unavailable.

    Blocking: performs a Postgres fetch + token decrypt on a cache miss, so call
    this off the event loop (e.g. via starlette.concurrency.run_in_threadpool).
    Callers should fall back to local filesystem storage when this returns None.
    """
    if not user_id:
        return None

    now = time.time()
    with _CACHE_LOCK:
        entry = _CACHE.get(user_id)
        if entry is not None:
            ts, drive = entry
            ttl = _TTL_OK if drive is not None else _TTL_NONE
            if now - ts < ttl:
                return drive

    drive = _build_drive_for_user(user_id)
    with _CACHE_LOCK:
        _CACHE[user_id] = (time.time(), drive)
    return drive


def _build_drive_for_user(user_id: str) -> Optional[DriveStorage]:
    """
    Load encrypted Drive tokens from Postgres, decrypt, and return DriveStorage.
    Returns None if:
      - No Drive tokens found for this user (not yet linked)
      - Postgres is not configured or unreachable (e.g. in tests)
      - Token decryption fails
    """
    try:
        row = fetchone(
            "select access_token_enc, refresh_token_enc, expires_at "
            "from user_drive_tokens where user_id = %s",
            (user_id,),
        )
        if not row:
            return None
    except Exception:
        return None

    try:
        access_token = decrypt(row["access_token_enc"])
        refresh_token = decrypt(row["refresh_token_enc"])
    except Exception:
        return None
    # psycopg parses a `timestamptz` column into a native tz-aware datetime, not
    # a string — DriveStorage expects an ISO string (matching what auth.py writes
    # via creds.expiry.isoformat()), so re-stringify here.
    expires_at_raw = row.get("expires_at")
    expires_at: Optional[str] = (
        expires_at_raw.isoformat() if hasattr(expires_at_raw, "isoformat") else expires_at_raw
    )

    def on_refresh(access_token: str, refresh_token: str, expires_at: Optional[str]):
        """Persist refreshed tokens back to Postgres."""
        from app.core.crypto import encrypt
        execute(
            """
            insert into user_drive_tokens (user_id, access_token_enc, refresh_token_enc, expires_at)
            values (%s, %s, %s, %s)
            on conflict (user_id) do update
              set access_token_enc = excluded.access_token_enc,
                  refresh_token_enc = excluded.refresh_token_enc,
                  expires_at = excluded.expires_at
            """,
            (user_id, encrypt(access_token), encrypt(refresh_token), expires_at),
        )

    return DriveStorage(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        user_id=user_id,
        on_token_refresh=on_refresh,
    )
