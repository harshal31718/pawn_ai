import os
from pathlib import Path

DATA_DIR = Path(os.getenv("PAWN_DATA_DIR", "/app/data"))

REGISTRY_DIR      = DATA_DIR / "registry"
MODELS_FILE       = REGISTRY_DIR / "models.json"
ENDPOINTS_FILE    = REGISTRY_DIR / "endpoints.json"
CONVERSATIONS_DIR = DATA_DIR / "conversations"
MEMORY_DIR        = DATA_DIR / "memory"
MEMORY_DB         = MEMORY_DIR / "memory.db"
RATE_LIMITS_DIR   = DATA_DIR / "rate_limits"
SESSION_FILE      = RATE_LIMITS_DIR / "session.json"
CHECKPOINTS_DB    = DATA_DIR / "checkpoints.db"

# --- Kaggle-backed generation (Plan v4 / imageLab) ---------------------------
# Bundled notebook templates PAWN deploys into the user's own Kaggle account.
KAGGLE_TEMPLATES_DIR = Path(__file__).resolve().parent / "kaggle_templates"
KAGGLE_CUBE_TEMPLATE = KAGGLE_TEMPLATES_DIR / "cube_poc" / "notebook.ipynb"

# Kaggle public REST API (the official `kaggle` CLI wraps this same base).
KAGGLE_API_BASE = "https://www.kaggle.com/api/v1"

# A kernel run is slow (queue + container start + execution). Poll until done.
KAGGLE_RUN_TIMEOUT_SECONDS = 600
KAGGLE_POLL_INTERVAL_SECONDS = 8
# Per-HTTP-call timeout (each individual push/status/output request).
KAGGLE_HTTP_TIMEOUT_SECONDS = 30

# Per-user kernel slug suffixes (full slug is "<username>/<suffix>").
KAGGLE_CUBE_SLUG = "pawn-cube-poc"

