import os
from pathlib import Path


def read_secret(name: str) -> str | None:
    path = Path(f"/run/secrets/{name}")
    if path.exists():
        return path.read_text(encoding="utf-8-sig").strip()
    return os.getenv(name.upper())


GEMINI_API_KEY      = read_secret("gemini_api_key")
CEREBRAS_API_KEY    = read_secret("cerebras_api_key")
HUGGINGFACE_API_KEY = read_secret("huggingface_api_key")
GITHUB_API_KEY      = read_secret("github_api_key")
OPENROUTER_API_KEY  = read_secret("openrouter_api_key")
