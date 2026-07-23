"""PAWN 2.0 Phase B.3: operator-owned shared pool key storage.

Mirrors key_store.py's encryption/caching pattern, but one row per PROVIDER
(no user_id -- this is the operator's shared key, not a per-user BYOK key).
Admin-editable live via routes/admin.py: writes evict the cache immediately so
an admin's edit takes effect on the very next request, no restart needed.
"""

import threading
import time
from typing import Optional

from app.core.crypto import decrypt, encrypt
from app.db.postgres_client import execute, fetchall, fetchone

# LLM providers eligible for a pool key -- mirrors the 11 Docker secrets
# wired in docker-compose.yml (Phase 1b). Deliberately excludes tavily/brave
# (search keys, not LLM providers -- pool sharing is LLM-quota-specific).
POOL_VALID_PROVIDERS = {
    "google",
    "groq",
    "cerebras",
    "huggingface",
    "github",
    "openrouter",
    "mistral",
    "nvidia",
    "zhipu",
    "sambanova",
    "kluster",
}

# Same short-TTL-cache-with-explicit-eviction pattern as key_store._KEY_CACHE --
# pool keys are read on every LLM call that might use the pool, so a Postgres
# round-trip per call isn't acceptable, but an admin's edit must still be live
# almost immediately (explicit eviction on write, not just TTL expiry).
_POOL_CACHE: dict[str, tuple[float, Optional[dict]]] = {}
_POOL_TTL = 60.0
_POOL_LOCK = threading.Lock()


def _cache_put(provider: str, config: Optional[dict]) -> None:
    with _POOL_LOCK:
        _POOL_CACHE[provider] = (time.time(), config)


def _evict(provider: str) -> None:
    with _POOL_LOCK:
        _POOL_CACHE.pop(provider, None)


def set_pool_key(provider: str, plain_key: str) -> None:
    """Encrypt and upsert the operator's shared key for a provider.
    Leaves `enabled`/`saturation_pct` untouched if the row already exists."""
    execute(
        """
        insert into pool_api_keys (provider, key_enc)
        values (%s, %s)
        on conflict (provider) do update set key_enc = excluded.key_enc, updated_at = now()
        """,
        (provider, encrypt(plain_key)),
    )
    _evict(provider)


def get_pool_key(provider: str) -> Optional[str]:
    """Fetch and decrypt the operator's pool key for a provider, or None if
    absent or disabled."""
    config = get_pool_config(provider)
    if config is None or not config["enabled"]:
        return None
    try:
        return decrypt(config["key_enc"])
    except Exception:
        return None


def get_pool_config(provider: str) -> Optional[dict]:
    """Raw row (still holds the ENCRYPTED key_enc, never call this to get a
    usable key -- use get_pool_key) plus enabled/saturation_pct, or None if no
    row exists for this provider."""
    now = time.time()
    with _POOL_LOCK:
        entry = _POOL_CACHE.get(provider)
        if entry is not None and now - entry[0] < _POOL_TTL:
            return entry[1]
    try:
        row = fetchone(
            "select provider, key_enc, enabled, saturation_pct from pool_api_keys where provider = %s",
            (provider,),
        )
    except Exception:
        row = None
    _cache_put(provider, row)
    return row


def list_pool_providers() -> list[dict]:
    """Every configured provider's admin-visible metadata (never the key
    itself) -- for GET /admin/pool-keys."""
    try:
        rows = fetchall(
            "select provider, enabled, saturation_pct, updated_at from pool_api_keys order by provider",
        )
        return rows
    except Exception:
        return []


def set_enabled(provider: str, enabled: bool) -> None:
    execute(
        "update pool_api_keys set enabled = %s, updated_at = now() where provider = %s",
        (enabled, provider),
    )
    _evict(provider)


def set_saturation_pct(provider: str, saturation_pct: Optional[int]) -> None:
    execute(
        "update pool_api_keys set saturation_pct = %s, updated_at = now() where provider = %s",
        (saturation_pct, provider),
    )
    _evict(provider)


def delete_pool_key(provider: str) -> None:
    execute("delete from pool_api_keys where provider = %s", (provider,))
    _evict(provider)
