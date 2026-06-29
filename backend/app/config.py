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

# Supabase (application database)
SUPABASE_URL         = read_secret("supabase_url")
SUPABASE_SERVICE_KEY = read_secret("supabase_service_key")
# Public anon key — injected into the warm Kaggle kernel (Phase W) so it can reach
# Supabase. PUBLIC by design; the master service_key is NEVER injected.
SUPABASE_ANON_KEY    = read_secret("supabase_anon_key")

# Encryption key for BYOK keys and Drive tokens (AES-256-GCM, 32-byte hex)
ENCRYPTION_SECRET = read_secret("encryption_secret")

# Google OAuth2
GOOGLE_CLIENT_ID     = read_secret("google_client_id")
GOOGLE_CLIENT_SECRET = read_secret("google_client_secret")

# JWT signing secret
JWT_SECRET = read_secret("jwt_secret")
