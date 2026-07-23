import os
from functools import lru_cache
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
# every user of this deployment, supplied by whoever runs the container via
# Docker secrets (never Postgres, never the frontend). "Self-hosted pool" per
# the plan's locked design: the operator uses their own free-tier signups, so
# this is personal free-tier consumption from the operator's perspective, not
# proxying inference to strangers on someone else's key -- re-examine this
# design before ever pointing one shared instance at the public internet.
#
# `lru_cache` is safe (not just an optimization): secrets are read from files
# mounted at container start, or env vars set at process start -- neither
# changes without a restart, which invalidates the cache along with it.
@lru_cache(maxsize=None)
def read_pool_key(provider: str) -> str | None:
    """Read the operator's shared pool key for `provider`, or None if the
    operator hasn't configured one. Looked up as secret name
    `pool_<provider>_api_key` (e.g. `pool_groq_api_key`), matching
    `secrets/pool_<provider>_api_key.example`."""
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
