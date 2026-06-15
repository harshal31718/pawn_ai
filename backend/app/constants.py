import os
from pathlib import Path

DATA_DIR = Path(os.getenv("PAWN_DATA_DIR", "/app/data"))

REGISTRY_DIR      = DATA_DIR / "registry"
MODELS_FILE       = REGISTRY_DIR / "models.json"
ENDPOINTS_FILE    = REGISTRY_DIR / "endpoints.json"
CONVERSATIONS_DIR = DATA_DIR / "conversations"
MEMORY_DIR        = DATA_DIR / "memory"
MEMORY_INDEX      = MEMORY_DIR / "index.json"
RATE_LIMITS_DIR   = DATA_DIR / "rate_limits"
SESSION_FILE      = RATE_LIMITS_DIR / "session.json"
