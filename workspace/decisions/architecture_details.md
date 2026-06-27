# Architecture
## Tech Stack, Directory Structure, Design Decisions

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React + Vite + TypeScript + Tailwind v4 |
| Backend | FastAPI (Python 3.12), async everywhere |
| Streaming | Server-Sent Events (SSE), typed event protocol |
| Provider layer | URL-routing via `_detect_provider(url)` → provider client |
| Model registry | JSON files in `data/registry/` — data, not code |
| Rate limit state | In-memory per process, rolling windows, initialized at zero on startup |
| Agent framework | LangGraph + JSON/ReAct tool protocol |
| RAG | sqlite-vec (`vec0` virtual table) + FTS5 full-text search, fused with Reciprocal Rank Fusion (RRF) |
| Embeddings | `text-embedding-004` (Gemini embedding API) behind swappable interface |
| Memory storage | Local `data/` → Google Drive in Phase 2 |
| Auth | None in Phase 1–3 → Google OAuth2 in Phase 4 |
| Secrets | Docker secret files mounted at `/run/secrets/*` — never `.env`, never hardcoded |
| Runtime | Docker + docker-compose |

---

## Directory Structure

```
pawn/
├── backend/
│   ├── app/
│   │   ├── main.py                  ← slim orchestrator: middleware stack, lifespan, router wiring
│   │   ├── constants.py             ← DATA_DIR from env; all derived paths (registry, conversations, memory)
│   │   ├── app_initializer.py       ← initialize_managers() → dict; all singletons built once
│   │   ├── exceptions.py            ← domain exceptions (ProviderError, NoEndpointError, etc.) + HTTP handlers
│   │   ├── events.py                ← typed SSE event builder functions
│   │   │
│   │   ├── core/
│   │   │   ├── llm_core.py          ← stream_llm(url, model, messages, headers), _detect_provider,
│   │   │   │                           _provider_headers, stream_llm_with_fallback, shared httpx.AsyncClient
│   │   │   └── rate_limiter.py      ← EndpointRateLimiter: rolling windows, 90% threshold, cooldowns
│   │   │
│   │   ├── registry/
│   │   │   ├── schemas.py           ← Pydantic: ModelEntry, EndpointEntry
│   │   │   ├── loader.py            ← load_registry(); typed accessors: get_model, endpoints_for, user_models
│   │   │   └── seed.py              ← writes initial models.json + endpoints.json if absent
│   │   │
│   │   ├── resolver/
│   │   │   └── resolver.py          ← Resolver.pick(model_id) → [(url, model_name, headers), ...]
│   │   │
│   │   ├── memory/
│   │   │   ├── embed.py             ← abstract embed(text) → list[float]; impl: text-embedding-004
│   │   │   ├── index.py             ← add_chunk(conv_id, text); builds index.json
│   │   │   └── retrieve.py          ← retrieve(query, top_k) → list[MemoryChunk]; brute-force cosine
│   │   │
│   │   ├── agent/
│   │   │   ├── graph.py             ← LangGraph StateGraph; nodes call core/llm_core.py
│   │   │   ├── parser.py            ← JSON/ReAct response parser with fallback
│   │   │   └── routing.py           ← PURPOSE_TO_LEVEL capability map
│   │   │
│   │   ├── storage/
│   │   │   └── conversations.py     ← all file I/O for conversation data (meta, messages, summary)
│   │   │
│   │   ├── middleware/
│   │   │   ├── security.py          ← SecurityHeadersMiddleware (CSP, X-Frame-Options, Referrer-Policy)
│   │   │   └── timeout.py           ← RequestTimeoutMiddleware (45s, SSE paths exempt)
│   │   │
│   │   └── routes/
│   │       ├── chat.py              ← setup_chat_routes(deps)
│   │       ├── registry.py          ← setup_registry_routes(deps)
│   │       ├── conversations.py     ← setup_conversation_routes(deps)
│   │       └── upload.py            ← setup_upload_routes(deps)
│   │
│   ├── tests/
│   ├── data/                        ← gitignored (personal data, like secrets/)
│   │   ├── registry/
│   │   │   ├── models.json
│   │   │   └── endpoints.json
│   │   ├── conversations/
│   │   ├── memory/
│   │   │   └── memory.db            ← sqlite-vec: vec0 + FTS5 + chunks tables
│   │   ├── checkpoints.db           ← LangGraph AsyncSqliteSaver checkpoints
│   │   └── rate_limits/
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   │   └── client.ts            ← all fetch/SSE calls; no inline fetch in components
│   │   ├── components/
│   │   │   ├── ChatWindow.tsx
│   │   │   ├── MessageInput.tsx
│   │   │   ├── Message.tsx          ← provider badge on assistant bubbles
│   │   │   ├── ModelSwitcher.tsx    ← fetches GET /registry/models; groups by capability level
│   │   │   ├── Sidebar.tsx          ← conversation list, new/switch/delete
│   │   │   └── TracePanel.tsx       ← collapsible agent step events
│   │   ├── types.ts
│   │   └── App.tsx
│   ├── package.json
│   ├── .env.example
│   └── Dockerfile
│
├── secrets/                         ← gitignored; real API keys as files
│   ├── .gitkeep
│   ├── gemini_api_key.example
│   ├── cerebras_api_key.example
│   ├── huggingface_api_key.example
│   ├── github_api_key.example
│   └── openrouter_api_key.example
│
├── .claude/
│   ├── CLAUDE.md
│   ├── rules/
│   │   ├── backend.md
│   │   └── frontend.md
│   ├── agents/
│   │   ├── code-reviewer.md
│   │   ├── security-auditor.md
│   │   └── test-runner.md
│   ├── skills/
│   │   └── build-step/SKILL.md
│   └── settings.json
│
├── workspace/
│   └── dev-log.md
├── docker-compose.yml
├── .gitignore
└── README.md
```

---

## Core Architectural Patterns

These patterns are validated design decisions. Every pattern below is adopted as-is
unless noted.

### 1. constants.py — single source of truth for paths

```python
# backend/app/constants.py
import os
from pathlib import Path

DATA_DIR = Path(os.getenv("PAWN_DATA_DIR", "/app/data"))

REGISTRY_DIR    = DATA_DIR / "registry"
MODELS_FILE     = REGISTRY_DIR / "models.json"
ENDPOINTS_FILE  = REGISTRY_DIR / "endpoints.json"
CONVERSATIONS_DIR = DATA_DIR / "conversations"
MEMORY_DIR        = DATA_DIR / "memory"
MEMORY_DB         = MEMORY_DIR / "memory.db"
RATE_LIMITS_DIR   = DATA_DIR / "rate_limits"
SESSION_FILE      = RATE_LIMITS_DIR / "session.json"
CHECKPOINTS_DB    = DATA_DIR / "checkpoints.db"
```

`DATA_DIR` reads one env var. Everything else derives from it. No `os.path.join("data", "x")` at call sites ever.

### 2. initialize_managers() — dependency injection, no module-level globals

```python
# backend/app/app_initializer.py

def initialize_managers() -> dict:
    registry = load_registry()
    rate_limiter = EndpointRateLimiter(registry.endpoints)
    resolver = Resolver(registry, rate_limiter)
    return {
        "registry": registry,
        "rate_limiter": rate_limiter,
        "resolver": resolver,
    }
```

All singletons built once at startup. `main.py` unpacks the dict and passes dependencies
to router factories. Routers never import managers as globals.

### 3. Router factories

```python
# backend/app/routes/chat.py

def setup_chat_routes(resolver: Resolver, rate_limiter: EndpointRateLimiter) -> APIRouter:
    router = APIRouter()
    # route definitions here, closing over injected deps
    return router
```

Each router is a factory receiving its dependencies at wiring time.

### 4. URL-routing via _detect_provider(url)

Provider detection from URL hostname — not from an explicit provider string the caller must
manage. The caller hands over a URL; the core figures out payload shape, headers, and
parsing.

```python
def _detect_provider(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower()
    if "anthropic" in host:
        return "anthropic"
    return "openai_compatible"   # everything else, including Google's OAI-compat endpoint
```

Google's OpenAI-compatible endpoint (`generativelanguage.googleapis.com/v1beta/openai`)
routes as `openai_compatible` — zero special cases.

### 5. Fallback chain (llm_core)

```python
async def stream_llm_with_fallback(
    candidates: list[tuple[str, str, dict]],  # (url, model_name, headers)
    messages: list,
    on_switch: Callable | None = None,
) -> AsyncGenerator[str, None]:
    for i, (url, model, headers) in enumerate(candidates):
        try:
            async for token in stream_llm(url, model, messages, headers):
                yield token
            return
        except ProviderError as e:
            if e.kind == "rate_limit" and i < len(candidates) - 1:
                if on_switch:
                    on_switch(candidates[i + 1])
                continue
            raise
    raise NoEndpointError("All endpoints exhausted")
```

### 6. Dead-host cooldown

2 consecutive connect failures → 20s cooldown on that host. Subsequent calls fail fast
instead of waiting on the TCP timeout. Tracked in `EndpointRateLimiter.consecutive_failures`.
Complementary to the rate-limit cooldown — these are different failure modes:
- Rate-limit cooldown: provider returned 429 (quota)
- Dead-host cooldown: provider unreachable (connectivity)

### 7. Shared httpx.AsyncClient

One process-wide async HTTP client, lazy-initialized in `llm_core.py`. Keeps TCP/TLS
connections warm across requests.

### 8. _sanitize_llm_messages

Strips non-standard fields, repairs orphaned tool messages (tool result without preceding
tool_call), merges consecutive user messages. Applied before every provider call.

### 9. _format_upstream_error

Turns raw HTTP errors into user-readable sentences:
- 401 → "API key rejected by [provider] — check your key in settings"
- 429 → "Rate limit reached on [provider] — switching to next endpoint"
- 5xx → "[Provider] returned a server error — retrying on next endpoint"

### 10. SecurityHeadersMiddleware + RequestTimeoutMiddleware

- `SecurityHeadersMiddleware`: adds CSP, X-Frame-Options, Referrer-Policy on every response
- `RequestTimeoutMiddleware`: kills hung requests at 45s; SSE paths are whitelisted (exempt)

### 11. GZipMiddleware

Starlette's `GZipMiddleware` excludes `text/event-stream` by default — SSE is never
compressed or buffered. Cuts JS/CSS by ~80%.

---

## Design Decisions Locked

These decisions are fixed. They do not need to be re-debated at implementation time.

| Decision | Choice | Reason |
|---|---|---|
| Start | From scratch | Clean slate; new repo at `/PAWN` |
| Provider routing | URL-routing (`_detect_provider(url)`) | Adding providers is config, not code |
| Google / Gemini | OpenAI-compatible REST endpoint | Eliminates Google SDK; zero special cases |
| normalize.py public API | `chat_stream(model_id, messages)` | Callers use canonical model ID only |
| Registry storage | JSON files in `data/registry/` | Data, not DB; file edit to add a model |
| Rate limit state | In-memory, initialized at zero per restart | No persistence needed; simple and correct |
| Rate limit class name | `EndpointRateLimiter` | Tracks outbound quota vs providers (not inbound) |
| Frontend | React + Vite + TypeScript + Tailwind v4 | SSE state, provider badges, model switcher complexity |
| Vector memory | In-memory cosine similarity | No ChromaDB dependency; single-user index fits in RAM |
| Auth | None until Phase 4 | Single-user tool; auth middleware adds complexity with no benefit |
| Secrets | Docker secret files, `/run/secrets/*` | Never `.env`, never hardcoded |
| Dependency injection | `initialize_managers()` + router factories | No module-level globals |

---

## Patterns Deliberately Skipped

| Pattern | Why Skipped |
|---|---|
| SQLite endpoint table | Registry is JSON; no dynamic UI for adding endpoints |
| Auth middleware (bcrypt, sessions, cookies) | Single user; no multi-user until Phase 4 |
| Per-user owner scoping in every query | No multi-user means no owner filtering |
| Model discovery / port scanning | Static JSON registry; no dynamic probing |
| ChromaDB for vector memory | External dependency not needed at single-user scale |
| Google genai SDK for Gemini | Replaced by Google's OpenAI-compatible REST endpoint |
| Separate "internal" WebSocket provider | All providers go through OAI-compat REST; fast models route by capability level |
