"""Per-user BYOK (Bring Your Own Key) provider API key storage.

Keys are encrypted with AES-256-GCM (via app.core.crypto) before being stored in
the Supabase `user_api_keys` table, and decrypted only inside the backend when
proxying an LLM call. Plaintext keys never leave the backend and are never
returned to the frontend — list_providers() returns provider names only.

All reads are exception-safe: get_key()/list_providers() return None/[] if
Supabase is unavailable, so the resolver can fall back to shared Docker secrets.
"""

import sys
from typing import List, Optional

from app.core.crypto import decrypt, encrypt
from app.db.supabase_client import get_db

# Providers a user may supply a key for (mirrors the resolver/secret names).
VALID_PROVIDERS = {
    "google",
    "groq",
    "cerebras",
    "huggingface",
    "github",
    "openrouter",
}


def set_key(user_id: str, provider: str, plain_key: str) -> None:
    """Encrypt and upsert a user's API key for a provider."""
    db = get_db()
    db.table("user_api_keys").upsert(
        {
            "user_id": user_id,
            "provider": provider,
            "key_enc": encrypt(plain_key),
        }
    ).execute()


def get_key(user_id: str, provider: str) -> Optional[str]:
    """Fetch and decrypt a user's API key for a provider, or None if absent."""
    try:
        db = get_db()
        result = (
            db.table("user_api_keys")
            .select("key_enc")
            .eq("user_id", user_id)
            .eq("provider", provider)
            .single()
            .execute()
        )
        if not result.data:
            return None
        return decrypt(result.data["key_enc"])
    except Exception:
        return None


def list_providers(user_id: str) -> List[str]:
    """Return the list of providers this user has a key configured for.

    Never returns key values — provider names only.
    """
    try:
        db = get_db()
        result = (
            db.table("user_api_keys")
            .select("provider")
            .eq("user_id", user_id)
            .execute()
        )
        return [row["provider"] for row in (result.data or [])]
    except Exception as e:
        print(f"Failed to list user API key providers: {e}", file=sys.stderr)
        return []


def delete_key(user_id: str, provider: str) -> None:
    """Delete a user's API key for a provider."""
    db = get_db()
    db.table("user_api_keys").delete().eq("user_id", user_id).eq(
        "provider", provider
    ).execute()
