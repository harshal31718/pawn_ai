"""Per-user BYOK (Bring Your Own Key) provider API key storage.

Keys are encrypted with AES-256-GCM (via app.core.crypto) before being stored in
the Postgres `user_api_keys` table, and decrypted only inside the backend when
proxying an LLM call. Plaintext keys never leave the backend and are never
returned to the frontend — list_providers() returns provider names only.

All reads are exception-safe: get_key()/list_providers() return None/[] if
Postgres is unavailable, so the resolver can fall back to shared Docker secrets.
"""

import json
import sys
import threading
import time
from typing import List, Optional

from app.config import SHARED_DB_DSN
from app.core.crypto import decrypt, encrypt
from app.db import postgres_client
# Providers a user may supply a key for -- 2026-07-23: derived from the
# provider registry (data/registry/providers_*.json) instead of a hand-kept
# copy. Includes "kaggle" now (didn't before) -- harmless, since the
# dedicated /keys/kaggle route is registered before the generic
# /keys/{provider} catch-all and always intercepts that literal path first.
from app.registry.providers import VALID_PROVIDER_IDS as VALID_PROVIDERS


# PAWN 2.0 Phase E.4: user_api_keys lives on SHARED_DB_DSN (defaults to
# POSTGRES_DSN -- prod is unaffected), not the per-environment POSTGRES_DSN
# every other table uses. Thin wrappers so every existing call site below
# (execute(...)/fetchall(...)/fetchone(...)) picks this up automatically
# instead of needing a `dsn=` kwarg threaded through each one individually.
def execute(sql, params=()):
    return postgres_client.execute(sql, params, dsn=SHARED_DB_DSN)


def fetchall(sql, params=()):
    return postgres_client.fetchall(sql, params, dsn=SHARED_DB_DSN)


def fetchone(sql, params=()):
    return postgres_client.fetchone(sql, params, dsn=SHARED_DB_DSN)

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
        rows = fetchall(
            "select provider, key_enc from user_api_keys where user_id = %s",
            (user_id,),
        )
    except Exception:
        return
    for row in rows:
        try:
            _cache_put(user_id, row["provider"], decrypt(row["key_enc"]))
        except Exception:
            pass


def set_key(user_id: str, provider: str, plain_key: str) -> None:
    """Encrypt and upsert a user's API key for a provider."""
    execute(
        """
        insert into user_api_keys (user_id, provider, key_enc)
        values (%s, %s, %s)
        on conflict (user_id, provider) do update set key_enc = excluded.key_enc
        """,
        (user_id, provider, encrypt(plain_key)),
    )
    _evict(user_id, provider)


def has_search_key(user_id: Optional[str]) -> bool:
    """True if the user has a Tavily or Brave key configured (agent tools /
    A.3). Single source of truth for this check -- the router (A.5), the
    main tool registry (A.4), and the researcher subagent (A.7) all gate
    web_search access on it and must agree."""
    return bool(get_key(user_id, "tavily") or get_key(user_id, "brave"))


def get_key(user_id: str, provider: str) -> Optional[str]:
    """Fetch and decrypt a user's API key for a provider, or None if absent."""
    now = time.time()
    with _KEY_LOCK:
        entry = _KEY_CACHE.get((user_id, provider))
        if entry is not None and now - entry[0] < _KEY_TTL:
            return entry[1]
    try:
        row = fetchone(
            "select key_enc from user_api_keys where user_id = %s and provider = %s",
            (user_id, provider),
        )
        key = decrypt(row["key_enc"]) if row else None
    except Exception:
        key = None
    _cache_put(user_id, provider, key)
    return key


def list_providers(user_id: str) -> List[str]:
    """Return the list of providers this user has a key configured for.

    Never returns key values — provider names only.
    """
    try:
        rows = fetchall(
            "select provider from user_api_keys where user_id = %s",
            (user_id,),
        )
        return [row["provider"] for row in rows]
    except Exception as e:
        print(f"Failed to list user API key providers: {e}", file=sys.stderr)
        return []


def delete_key(user_id: str, provider: str) -> None:
    """Delete a user's API key for a provider."""
    execute(
        "delete from user_api_keys where user_id = %s and provider = %s",
        (user_id, provider),
    )
    _evict(user_id, provider)


# --- Kaggle config (dict payload) -------------------------------------------
# Unlike LLM providers (single string key), Kaggle needs a structured payload
# (username + api_token + managed kernel slugs). It is JSON-encoded, encrypted
# with the same AES-GCM path, and stored in the same `user_api_keys` table under
# provider="kaggle". Not cached (read once per slow generation — caching adds no
# value and would pollute the str-typed key cache).

_KAGGLE_PROVIDER = "kaggle"


def set_kaggle(user_id: str, config: dict) -> None:
    """Encrypt and upsert the user's Kaggle config dict."""
    execute(
        """
        insert into user_api_keys (user_id, provider, key_enc)
        values (%s, %s, %s)
        on conflict (user_id, provider) do update set key_enc = excluded.key_enc
        """,
        (user_id, _KAGGLE_PROVIDER, encrypt(json.dumps(config))),
    )


def has_kaggle_creds(user_id: Optional[str]) -> bool:
    """True if the user has both a Kaggle username and API token configured
    (F-1's generate_image agent tool gates on this — same single-source-of-
    truth pattern as has_search_key)."""
    cfg = get_kaggle(user_id) if user_id else None
    return bool(cfg and cfg.get("username") and cfg.get("api_token"))


def get_kaggle(user_id: str) -> Optional[dict]:
    """Fetch and decrypt the user's Kaggle config dict, or None if absent."""
    try:
        row = fetchone(
            "select key_enc from user_api_keys where user_id = %s and provider = %s",
            (user_id, _KAGGLE_PROVIDER),
        )
        if not row:
            return None
        return json.loads(decrypt(row["key_enc"]))
    except Exception:
        return None


def delete_kaggle(user_id: str) -> None:
    """Delete the user's Kaggle config."""
    execute(
        "delete from user_api_keys where user_id = %s and provider = %s",
        (user_id, _KAGGLE_PROVIDER),
    )
