"""Factory for creating per-user DriveStorage instances.

Fetches encrypted Drive tokens from Supabase, decrypts them,
and returns a ready-to-use DriveStorage object.

Usage in a FastAPI route:
    from app.core.drive_factory import get_drive_for_user
    drive = get_drive_for_user(request.state.user_id)
"""

from typing import Optional

from app.core.crypto import decrypt
from app.db.supabase_client import get_db
from app.storage.drive import DriveStorage


def get_drive_for_user(user_id: str) -> Optional[DriveStorage]:
    """
    Load encrypted Drive tokens from Supabase, decrypt, and return DriveStorage.
    Returns None if:
      - No Drive tokens found for this user (not yet linked)
      - Supabase is not configured or unreachable (e.g. in tests)
      - Token decryption fails
    Callers should fall back to local filesystem storage when this returns None.
    """
    try:
        db = get_db()
        result = (
            db.table("user_drive_tokens")
            .select("access_token_enc, refresh_token_enc, expires_at")
            .eq("user_id", user_id)
            .single()
            .execute()
        )
        if not result.data:
            return None
    except Exception:
        return None

    try:
        row = result.data
        access_token = decrypt(row["access_token_enc"])
        refresh_token = decrypt(row["refresh_token_enc"])
    except Exception:
        return None
    expires_at: Optional[str] = row.get("expires_at")

    def on_refresh(access_token: str, refresh_token: str, expires_at: Optional[str]):
        """Persist refreshed tokens back to Supabase."""
        from app.core.crypto import encrypt
        db.table("user_drive_tokens").upsert(
            {
                "user_id": user_id,
                "access_token_enc": encrypt(access_token),
                "refresh_token_enc": encrypt(refresh_token),
                "expires_at": expires_at,
            }
        ).execute()

    return DriveStorage(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        user_id=user_id,
        on_token_refresh=on_refresh,
    )
