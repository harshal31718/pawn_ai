import os
from pathlib import Path


def read_secret(name: str) -> str | None:
    path = Path(f"/run/secrets/{name}")
    if path.exists():
        return path.read_text(encoding="utf-8-sig").strip()
    return os.getenv(name.upper())


# Provider API keys (shared app keys; users can override via BYOK)
GEMINI_API_KEY      = read_secret("gemini_api_key")
CEREBRAS_API_KEY    = read_secret("cerebras_api_key")
GROQ_API_KEY        = read_secret("groq_api_key")
HUGGINGFACE_API_KEY = read_secret("huggingface_api_key")
GITHUB_API_KEY      = read_secret("github_api_key")
OPENROUTER_API_KEY  = read_secret("openrouter_api_key")

# Self-hosted Postgres (application database) — replaces Supabase.
POSTGRES_DSN = read_secret("postgres_dsn")

# Public HTTPS URL for the self-hosted PostgREST instance (D.4) — injected into
# the warm Kaggle kernel payload so it can rendezvous with PAWN over the
# internet. Non-secret (just a URL); PostgREST itself has no host port and is
# only reachable via this reverse-proxied path. Anonymous requests to it get
# the restricted `pawn_anon` Postgres role (see supabase/schema.sql) — same
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
