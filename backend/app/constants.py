import os
from pathlib import Path

DATA_DIR = Path(os.getenv("PAWN_DATA_DIR", "/app/data"))

REGISTRY_DIR      = DATA_DIR / "registry"
MODELS_FILE       = REGISTRY_DIR / "models.json"
ENDPOINTS_FILE    = REGISTRY_DIR / "endpoints.json"
# Static bundled data (versioned with the code, never written to at runtime,
# no seeding step) -- resolved relative to the source tree like
# KAGGLE_TEMPLATES_DIR below, NOT under the isolatable DATA_DIR. models.json/
# endpoints.json above are genuinely user-mutable registry state (rewritten by
# registry-refresh, isolated per test worker); presets aren't, so they don't
# need or want that isolation.
IMAGE_PRESETS_FILE = Path(__file__).resolve().parent.parent / "data" / "registry" / "image_presets.json"
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
# can run well past a few minutes depending on Kaggle's network/GPU queue. Only
# reached when the Kaggle kernel-status probe below returns nothing usable (no
# creds, Kaggle API unreachable) or reports the kernel still 'queued' — the
# probe's own detection windows below are the normal, much faster path.
IMAGE_SESSION_STARTUP_TIMEOUT_SECONDS = 900
# Minimum interval between GET /kernels/status calls for the same warmup
# session — the frontend polls session status every 3s, but Kaggle's own API
# doesn't need hammering that hard just to detect a dead kernel.
IMAGE_SESSION_KAGGLE_PROBE_INTERVAL_SECONDS = 30
# Don't probe Kaggle for a session younger than this — a kernel needs a moment
# to actually start after push, and it's not worth the API call before then.
IMAGE_SESSION_STARTUP_PROBE_AFTER_SECONDS = 60
# Kaggle reports the kernel as 'running' but it has never landed a single
# heartbeat past this long during warmup -- the kernel is alive but can't reach
# PAWN's database at all (tunnel down, RLS token mismatch, writes rejected).
# The cell-0 supervisor heartbeats within seconds of container start on a
# healthy notebook, so this window is generous, not tight.
IMAGE_SESSION_RUNNING_NO_HEARTBEAT_TIMEOUT_SECONDS = 180
# Hard backstop on a session's duration (Kaggle's max batch run-time guardrail).
IMAGE_SESSION_MAX_DURATION_MINUTES = 120
# Backend/UI poll cadence while waiting for a durable job to finish.
IMAGE_JOB_POLL_INTERVAL_SECONDS = 3
# A cold one-shot job 'running' longer than this lost its worker (e.g. a backend
# restart) — reaped to 'error' so the monitor panel never hangs on a ghost.
COLD_JOB_MAX_WALLCLOCK_SECONDS = 1200

# --- Memory scoping (Phase M) -------------------------------------------------
# Chunk size for RAG indexing, approximated as len(text) // 4 (no tokenizer dep).
MEMORY_CHUNK_TOKENS = 400
MEMORY_CHUNK_OVERLAP_TOKENS = 50
# How long an in-process resolve_scope() result is trusted before re-walking
# Drive folder placement (explicitly evicted on a chat move — see M.5).
SCOPE_CACHE_TTL_SECONDS = 300
# Default number of memory chunks retrieve() returns per query.
MEMORY_TOP_K = 4

# --- Chat agent refinement (Phase A) ------------------------------------------
# Per-tool-call wall-clock budget. A tool that exceeds this (or raises) never
# crashes the graph — run_tool() converts it into a "TOOL_ERROR: ..." observation.
TOOL_TIMEOUT_SECONDS = 20
# web_search: cap on results returned to the model (keeps the observation small).
# O.2 (reply-quality plan, RC-2 fix) bumped 5 -> 8: heavy research needs more
# candidates to fetch full bodies from, not just more snippets to skim.
WEB_SEARCH_MAX_RESULTS = 8
# fetch_url: extracted page text is truncated to this many characters.
FETCH_MAX_CHARS = 8000
# O.2: auto-fetch the top N web_search results' full page bodies (via the
# same guarded fetch_url path) instead of returning search-engine snippets
# only -- the model was never seeing the text that actually contains named
# figures/dates/entities. Bounded to keep this cheap; the remaining results
# still return as snippets.
WEB_SEARCH_FETCH_TOP_N = 3
# Each auto-fetched body is truncated to this many characters (smaller than
# FETCH_MAX_CHARS since up to WEB_SEARCH_FETCH_TOP_N of these are
# concatenated into one web_search observation).
WEB_SEARCH_FETCH_CHARS_PER_RESULT = 2000
# Per-fetch bound on each auto-fetched result (found live: a slow/redirect-
# heavy page's fetch_url-style GET, with up to 3 redirect hops at 15s each,
# can run well past TOOL_TIMEOUT_SECONDS on its own -- run_tool's *outer*
# 20s budget wraps the whole web_search call, so one slow fetch used to
# discard ALL results (even ones that already succeeded) instead of
# degrading just that one result to its snippet. Fetches run concurrently
# (asyncio.gather), so this bounds wall-clock by the slowest single fetch,
# not their sum -- comfortably under TOOL_TIMEOUT_SECONDS alongside the
# initial search-API round-trip.
WEB_SEARCH_FETCH_TIMEOUT_SECONDS = 10

# Model router (A.5): heuristic-tier thresholds on total user-message text
# length. Above HEAVY -> always heavy; below LIGHT (and no other heavy
# trigger fired) -> light; the band between the two defers to the LLM
# fallback tier.
ROUTER_HEAVY_CHAR_THRESHOLD = 1500
ROUTER_LIGHT_CHAR_THRESHOLD = 200

# Per-role capability level, resolved through
# resolver.pick_model_by_capability(level, require_tools=...). The user's
# explicit model pick (ModelSwitcher) always wins for the final answer
# regardless of this table; every internal call (orchestrator, subagents,
# summarizer, titler) goes through it.
ROLE_LEVELS = {
    "orchestrator": "balanced",
    "final_light": "fast",
    "final_heavy": "research",
    "summarizer": "fast",
    "titler": "fast",
    "subagent_researcher": "fast",
    "subagent_coder": "research",
    "subagent_summarizer": "fast",
    # F-11: direct_answer_node's image-attached branch -- always overrides
    # the user's own model pick with a vision-capable one, filtered via
    # Resolver.pick_model_by_capability(require_vision=True).
    "vision_answer": "balanced",
    # Q3.1 (imageLab): vision_enhance.enhance_with_vision's Groq-then-Gemini
    # chain -- same require_vision=True filter as vision_answer, reused
    # rather than a new mechanism per plan_vision_prompt_enhancement.md §5.
    "vision_enhancer_primary": "balanced",
}

# Q3.1: below this word count, a raw prompt is considered "vague" and worth
# running through the vision enhancer; at/above it, _looks_already_scaffolded
# decides instead. Starting guess per phase_Q3_prompting_presets.md §3.1.4 --
# tune against the Q1.5 benchmark set if this misfires in practice.
ENHANCE_SKIP_WORD_THRESHOLD = 25

# Orchestrator (A.6) execute-loop bounds. Iteration cap stops a runaway tool
# loop; token budget is the sum of `usage.total_tokens` across every internal
# chat_complete call this request makes (plan + each execute iteration).
# Either cap being hit appends a "budget exhausted" system nudge and proceeds
# to final rather than erroring.
AGENT_MAX_ITERATIONS = 8
AGENT_MAX_TOKENS = 24000

# Preset subagents (A.7): each delegate_<name> call runs its own bounded tool
# loop, sharing the parent's AGENT_MAX_TOKENS counter (one budget per request).
SUBAGENT_MAX_ITERATIONS = 5

# Trace persistence (A.8): cap on the number of trace entries kept on a
# persisted assistant message (oldest dropped first) — bounds messages.jsonl
# growth for a chat with a very long tool-log.
TRACE_MAX_ENTRIES = 50

# O.3 (reply-quality plan, RC-3 fix): plan-as-contract verifier. Bounds how
# many times the verify->execute revision loop can run for one turn (deep-
# research turns only -- see graph.py's route_after_execute gate) so a
# stubborn gap can't run away the request.
VERIFY_MAX_REVISIONS = 2

