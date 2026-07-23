import os
from pathlib import Path


def read_secret(name: str) -> str | None:
    path = Path(f"/run/secrets/{name}")
    # is_file(), not exists(): a Docker secret whose host source file is
    # missing can get bind-mounted as an empty directory (seen on Docker
    # Desktop/Windows) rather than failing `docker compose up` outright --
    # exists() would be True for that directory and read_text() would raise
    # IsADirectoryError instead of falling through to the env-var fallback.
    if path.is_file():
        return path.read_text(encoding="utf-8-sig").strip()
    return os.getenv(name.upper())


# Phase 1b: operator-supplied shared free-tier key pool. Distinct from
# key_store.py's per-user encrypted BYOK keys -- this is the SAME key for
# every user of this deployment. "Self-hosted pool" per the plan's locked
# design: the operator uses their own free-tier signups, so this is personal
# free-tier consumption from the operator's perspective, not proxying
# inference to strangers on someone else's key -- re-examine this design
# before ever pointing one shared instance at the public internet.
#
# PAWN 2.0 Phase B.4 (2026-07-23): DB-first, Docker secret as a bootstrap
# fallback. The `@lru_cache` Phase 1b had here is REMOVED -- it blocked live
# admin edits from ever taking effect (a cached None/stale key would survive
# forever). pool_key_store's own short-TTL cache (with explicit eviction on
# write) replaces it, so this is no longer a hot-path concern.
#
# Import-cycle guard: config.py must NOT import pool_key_store at module
# top -- config -> pool_key_store -> postgres_client -> config would cycle.
# Lazy import inside the function instead, same convention
# resolver._resolve_key already uses for `from app.config import read_pool_key`.
def read_pool_key(provider: str) -> str | None:
    """Read the operator's shared pool key for `provider`: Postgres
    (`pool_key_store`, admin-editable live) first, falling back to the Docker
    secret `pool_<provider>_api_key` (Phase 1b bootstrap, matching
    `secrets/pool_<provider>_api_key.example`) if no DB row exists. Returns
    None if neither is configured, or if the DB row exists but is disabled."""
    from app.core import pool_key_store
    db_config = pool_key_store.get_pool_config(provider)
    if db_config is not None:
        return pool_key_store.get_pool_key(provider)
    return read_secret(f"pool_{provider}_api_key")


# PAWN 2.0 Phase E.1: which deployment this process is. Not a secret — a plain
# label read once at startup that drives Drive-folder/Kaggle-slug isolation
# (constants.py) so the same Google account can be used for local/staging
# testing and production without the two writing into the same folders/kernels.
# Default is the SAFE side: "dev". docker-compose.prod.yml (both staging and
# prod .env files) sets this explicitly alongside its many other required
# values, so prod is never running on an implicit default in practice — but an
# ad-hoc/local run that forgets to set it lands on the isolated "PAWN-dev/"
# root instead of silently writing into real production data.
PAWN_ENV = os.getenv("PAWN_ENV", "dev")

# Self-hosted Postgres (application database) — replaces Supabase.
POSTGRES_DSN = read_secret("postgres_dsn")

# PAWN 2.0 Phase E.4: the ONE deliberately-shared store across dev/prod --
# API keys (user_api_keys, pool_api_keys). Defaults to POSTGRES_DSN, so prod
# (single DB) is completely unaffected. In dev, set this to prod's DB reached
# over an SSH tunnel (mirror the existing `pgrst-tunnel` docker-compose
# pattern) so keys entered once stay in sync across both environments --
# requires dev to also carry prod's ENCRYPTION_SECRET to decrypt the shared
# blobs (the one real security cost of this, accepted for a solo operator
# per the plan's risk #6). key_store.py / pool_key_store.py pass this as the
# `dsn` override on every call; every other table stays on POSTGRES_DSN.
SHARED_DB_DSN = read_secret("shared_db_dsn") or POSTGRES_DSN

# Public HTTPS URL for the self-hosted PostgREST instance (D.4) — injected into
# the warm Kaggle kernel payload so it can rendezvous with PAWN over the
# internet. Non-secret (just a URL); PostgREST itself has no host port and is
# only reachable via this reverse-proxied path. Anonymous requests to it get
# the restricted `pawn_anon` Postgres role (see postgres/schema.sql) — same
# permissive-anon-on-two-tables posture as the prior Supabase setup, scoped
# per-session JWT auth remains deferred (documented as mandatory before
# multi-user, unchanged from Phase W).
POSTGREST_PUBLIC_URL = os.getenv("POSTGREST_PUBLIC_URL", "")

# Encryption key for BYOK keys and Drive tokens (AES-256-GCM, 32-byte hex)
ENCRYPTION_SECRET = read_secret("encryption_secret")

# Google OAuth2
GOOGLE_CLIENT_ID     = read_secret("google_client_id")
GOOGLE_CLIENT_SECRET = read_secret("google_client_secret")

# JWT signing secret
JWT_SECRET = read_secret("jwt_secret")

# Deployment URLs (non-secret; env-var driven, default to today's local-dev values
# so `docker compose up` locally is unaffected by these existing).
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:5174")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5174")
OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "http://localhost:8001/auth/callback")
# Space-separated (CSP source-list syntax), not comma-separated like CORS_ORIGINS.
CSP_CONNECT_SRC = os.getenv("CSP_CONNECT_SRC", "http://localhost:8000")
