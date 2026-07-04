import os
from pathlib import Path

DATA_DIR = Path(os.getenv("PAWN_DATA_DIR", "/app/data"))

REGISTRY_DIR      = DATA_DIR / "registry"
MODELS_FILE       = REGISTRY_DIR / "models.json"
ENDPOINTS_FILE    = REGISTRY_DIR / "endpoints.json"
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
# Max time to wait for an in-flight run (e.g. the deploy warmup) to free the slug
# before pushing a new run, instead of immediately erroring "Kaggle is busy".
KAGGLE_BUSY_WAIT_TIMEOUT_SECONDS = 300

# Per-user kernel slug suffixes (full slug is "<username>/<suffix>").
KAGGLE_CUBE_SLUG = "pawn-cube-poc"

# --- Warm/persistent Kaggle image sessions (Plan v5 / Phase W) ---------------
# W.0 CPU echo notebook that proves the persistent loop + PostgREST rendezvous.
KAGGLE_SESSION_POC_TEMPLATE = KAGGLE_TEMPLATES_DIR / "session_poc" / "notebook.ipynb"
# Single slug for the W.0 POC kernel (full slug "<username>/<suffix>").
KAGGLE_SESSION_SLUG = "pawn-session-poc"
# How often the persistent kernel polls PostgREST for work / writes a heartbeat.
KAGGLE_SESSION_POLL_INTERVAL_SECONDS = 3
# A 'ready' session whose heartbeat is older than this is considered dead.
IMAGE_SESSION_HEARTBEAT_STALE_SECONDS = 90  # 3× typical FLUX inference time (~30–90 s)
# A session still stuck in starting/installing/loading_model past this long is
# considered dead (no heartbeat exists yet during this phase to check instead).
# Cold-start cost is deps install + multi-GB model weight download/load, which
# can run well past a few minutes depending on Kaggle's network/GPU queue.
IMAGE_SESSION_STARTUP_TIMEOUT_SECONDS = 900
# Hard backstop on a session's duration (Kaggle's max batch run-time guardrail).
IMAGE_SESSION_MAX_DURATION_MINUTES = 120
# Backend/UI poll cadence while waiting for a durable job to finish.
IMAGE_JOB_POLL_INTERVAL_SECONDS = 3
# A cold one-shot job 'running' longer than this lost its worker (e.g. a backend
# restart) — reaped to 'error' so the monitor panel never hangs on a ghost.
COLD_JOB_MAX_WALLCLOCK_SECONDS = 1200

