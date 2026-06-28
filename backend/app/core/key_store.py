"""Per-user BYOK (Bring Your Own Key) provider API key storage.

Keys are encrypted with AES-256-GCM (via app.core.crypto) before being stored in
the Supabase `user_api_keys` table, and decrypted only inside the backend when
proxying an LLM call. Plaintext keys never leave the backend and are never
returned to the frontend — list_providers() returns provider names only.

All reads are exception-safe: get_key()/list_providers() return None/[] if
Supabase is unavailable, so the resolver can fall back to shared Docker secrets.
"""

import sys
import threading
import time
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

# Short-lived in-memory cache of decrypted keys. resolver.pick() calls get_key()
# several times per chat (once per reasoning step / provider), and it runs inside
# the async event loop — without this each call is a blocking Supabase round-trip
# that stalls the loop. TTL is short because keys rarely change and set_key/
# delete_key evict explicitly.
_KEY_CACHE: dict[tuple[str, str], tuple[float, Optional[str]]] = {}
_KEY_TTL = 300.0
_KEY_LOCK = threading.Lock()


def _cache_put(user_id: str, provider: str, key: Optional[str]) -> None:
    with _KEY_LOCK:
        _KEY_CACHE[(user_id, provider)] = (time.time(), key)


def _evict(user_id: str, provider: str) -> None:
    with _KEY_LOCK:
        _KEY_CACHE.pop((user_id, provider), None)


def prefetch(user_id: str) -> None:
    """Load all of a user's keys into the cache in one query.

    Blocking — call off the event loop (run_in_threadpool) at the start of a chat
    so the resolver's later get_key() calls are all cache hits.
    """
    try:
        db = get_db()
        result = (
            db.table("user_api_keys")
            .select("provider, key_enc")
            .eq("user_id", user_id)
            .execute()
        )
    except Exception:
        return
    for row in (result.data or []):
        try:
            _cache_put(user_id, row["provider"], decrypt(row["key_enc"]))
        except Exception:
            pass


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
    _evict(user_id, provider)


def get_key(user_id: str, provider: str) -> Optional[str]:
    """Fetch and decrypt a user's API key for a provider, or None if absent."""
    now = time.time()
    with _KEY_LOCK:
        entry = _KEY_CACHE.get((user_id, provider))
        if entry is not None and now - entry[0] < _KEY_TTL:
            return entry[1]
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
        key = decrypt(result.data["key_enc"]) if result.data else None
    except Exception:
        key = None
    _cache_put(user_id, provider, key)
    return key


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
    _evict(user_id, provider)
