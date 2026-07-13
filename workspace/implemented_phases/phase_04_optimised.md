# PAWN — Optimised Plan to Completion (v2)

*Single-user · Local-first · BYOK · API-only LLMs*
*Current state: Phase 1, Step 7 (Typed SSE events) in progress*
*Created: 2026-06-17*

---

## What Changed from the Original Plan — and Why

Every decision below was re-evaluated against current best practice (June 2026).
A `[CHANGED]` tag marks every deviation from the original plan with a reason.
Unchanged decisions are confirmed correct and noted as such.

---

## 0. Current State Snapshot

| Item | Status |
|---|---|
| Steps 1–6 | ✅ Done and verified |
| Step 7 (Typed SSE) | 🔄 Active — next to build |
| Backend | FastAPI, `llm_core.py`, Gemini streaming working |
| Frontend | React + Vite 8 + TypeScript + Tailwind v4 |
| Tests | 4 passing |
| Missing files (vs final architecture) | `events.py`, `app_initializer.py`, `normalize.py`, `registry/`, `resolver/`, `memory/`, `agent/`, `storage/` |

---

## 1. Technology Decisions — Optimised

### 1.1 Provider Stack `[CHANGED: added Groq, reordered by speed]`

**Original:** Google (Gemini), Cerebras, HuggingFace, GitHub Models, OpenRouter

**Updated provider priority:**

| Priority | Provider | Models | Free Tier | Key |
|---|---|---|---|---|
| 1 | **Groq** | Llama 3.3 70B, Llama 3.1 8B | 30 RPM · 12K TPM · 1K RPD | `groq_api_key` |
| 2 | **Cerebras** | Llama 3.3 70B, Llama 3.1 8B | 30 RPM · ~1M tokens/day | `cerebras_api_key` |
| 3 | **Google** | Gemini 2.5 Flash, Gemini 2.5 Flash-Lite | 15 RPM · 250K TPM · 1.5K RPD | `gemini_api_key` |
| 4 | **HuggingFace** | Llama 3.3 70B, DeepSeek R1 | Varies | `huggingface_api_key` |
| 5 | **GitHub Models** | Llama 3.3 70B, DeepSeek R1 | 150 RPD | `github_api_key` |
| 6 | **OpenRouter** | Llama 3.3 70B:free, DeepSeek R1:free | 200 RPM (aggregated) | `openrouter_api_key` |

**Why:** Groq wasn't in the original plan but is now the best free fast-inference provider
(800+ tok/s via LPU hardware). Cerebras is the second-fastest (wafer-scale, ~2600 tok/s).
Both are fully OpenAI-compatible — zero extra code. Reordering by speed/reliability means
users always get the fastest available endpoint; automatic failover walks down the list.

**New secret file needed:** `secrets/groq_api_key` + `secrets/groq_api_key.example`

---

### 1.2 LangGraph Streaming `[CHANGED: use astream_events v2]`

**Original:** custom per-node SSE event emission via a shared event queue

**Updated:** use `graph.astream_events(input, version="v2")` natively

```python
# routes/chat.py — inside the streaming endpoint
async def generate():
    async for event in graph.astream_events(input_data, version="v2", config=config):
        kind = event["event"]
        if kind == "on_chat_model_stream":
            delta = event["data"]["chunk"].content
            if delta:
                yield token_event(delta)
        elif kind == "on_chain_start":
            node = event.get("name", "")
            if node in TRACE_NODES:
                yield step_event(TRACE_NODES[node])
    yield done_event(via_provider=...)
```

**Why:** `astream_events v2` is the current LangGraph standard (v1 deprecated). It unifies
token streaming, tool-call events, and node transitions into one generator — no custom
queue/callback wiring. Dramatically simpler than the original per-node emit pattern.

**Required SSE response header (add to chat route):**
```python
headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}
```
Without `X-Accel-Buffering: no`, Nginx or Docker Compose reverse proxies silently buffer
the entire response, defeating streaming and causing the UI to hang until completion.

---

### 1.3 LangGraph Persistence `[CHANGED: SQLite checkpointer]`

**Original:** no checkpointer; state managed manually per-request

**Updated:** `AsyncSqliteSaver` as the graph checkpointer

```python
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# In initialize_managers():
checkpointer = await AsyncSqliteSaver.from_conn_string(
    str(DATA_DIR / "checkpoints.db")
)
graph = build_agent_graph(resolver, rate_limiter).compile(checkpointer=checkpointer)
```

**Why:**
- Enables mid-conversation fault recovery (graph state survives container restart)
- `conversation_id` maps directly to LangGraph's `thread_id` — no parallel state management
- `AsyncSqliteSaver` is non-blocking; won't stall the FastAPI event loop
- Single-user means no SQLite write-concurrency concerns

> **Security:** use `langgraph-checkpoint-sqlite >= 3.0.1` (fixes CVE-2025-67644 SQL injection)

**New `constants.py` entries:**
```python
CHECKPOINTS_DB = DATA_DIR / "checkpoints.db"
```

---

### 1.4 RAG: Hybrid sqlite-vec `[CHANGED: replace index.json + numpy]`

**Original:** `data/memory/index.json` with brute-force numpy cosine similarity

**Updated:** `sqlite-vec` for vector search + SQLite FTS5 for keyword fallback

```sql
-- Schema in memory.db
CREATE VIRTUAL TABLE memory_vec USING vec0(embedding float[768])
CREATE TABLE chunks (id TEXT, conv_id TEXT, text TEXT, created_at TEXT)
CREATE VIRTUAL TABLE chunks_fts USING fts5(text, content='chunks', content_rowid='rowid')
```

**Hybrid retrieval:**
```python
async def retrieve(query: str, top_k: int = 3) -> list[MemoryChunk]:
    vec_hits  = sqlite_vec_search(query_embedding, top_k * 2)
    fts_hits  = fts5_search(query_keywords, top_k)
    return rrfusion_merge(vec_hits, fts_hits)[:top_k]  # Reciprocal Rank Fusion
```

**Why:** For single-user RAG:
- `sqlite-vec` is already optimised for brute-force at <50K chunk scale — tighter loop than Python numpy
- FTS5 hybrid search significantly improves RAG accuracy; keyword matching catches what vector similarity misses
- Single SQLite file — no corruption risk from a mid-write JSON index
- No extra install complexity (`pip install sqlite-vec` — pre-built wheels available)

**New requirement:** `sqlite-vec>=0.1.0`

---

### 1.5 Embedding Model `[CHANGED: dual strategy]`

**Original:** `text-embedding-004` (Gemini API) only

**Updated:** primary API + optional local fallback

- **Default:** `text-embedding-004` (Google API, 1,500 RPM free, 768-dim)
- **Optional fallback:** `nomic-embed-text` via local Ollama (`http://localhost:11434`)

```python
# memory/embed.py — swappable, same public interface
async def embed(text: str) -> list[float]:
    if EMBED_BACKEND == "gemini":
        return await _gemini_embed(text)
    elif EMBED_BACKEND == "ollama":
        return await _ollama_embed(text)

EMBED_DIM = 768  # both models produce 768-dim vectors — no re-indexing needed when swapping
```

**Decision:** API default (zero setup). Document Ollama option in README for offline use.

---

### 1.6 Frontend Streaming Markdown `[NEW — not in original plan]`

**Original plan:** raw text accumulation — no markdown rendering

**Updated:** `react-markdown` with token buffering

```typescript
// Message.tsx — buffer tokens, update DOM every 50ms (not per-token)
const bufferRef = useRef('')
const [displayContent, setDisplayContent] = useState('')

useEffect(() => {
  const interval = setInterval(() => {
    if (bufferRef.current !== displayContent) {
      setDisplayContent(bufferRef.current)
    }
  }, 50)
  return () => clearInterval(interval)
}, [])

// On token event: bufferRef.current += delta  ← no setState, no re-render
```

```tsx
<ReactMarkdown>{displayContent}</ReactMarkdown>
```

**Why:** AI responses are always markdown. Without rendering, users see `**bold**` and
` ```code``` ` as raw text. Token-by-token `setState` causes severe jank at 50+ tok/s.
The 50ms buffer window is imperceptible to users but cuts re-renders by ~20x.
`react-markdown` is 11KB gzipped.

**New dependency:** `npm install react-markdown`

---

### 1.7 PDF Extraction `[CHANGED: pypdf → pdfplumber]`

**Original:** `pypdf`

**Updated:** `pdfplumber` (MIT license, better layout accuracy)

**Why:** `pypdf` is fine for page splitting but produces poor text from complex PDFs with
columns or tables. `pdfplumber` (MIT, pure Python) handles these correctly — the most
common real-world upload case. `PyMuPDF` would be faster but its AGPL-3.0 license
conflicts with a potential future open-source release.

**Change:** replace `pypdf` with `pdfplumber` in `requirements.txt`

---

### 1.8 Conversation Storage `[UNCHANGED — confirmed correct]`

`data/conversations/<uuid>/meta.json + messages.jsonl + summary.md` is correct for
single-user local. JSONL is append-only — safe under power loss. No change needed.

---

### 1.9 Phase 2/3/4 `[EXPLICITLY DEFERRED]`

> **User requirement:** *single user and local with only APIs connected to LLMs*

Phase 2 (Google Drive), Phase 3 (Encryption), and Phase 4 (Multi-user/Auth) are
**deferred indefinitely**. Local `data/` is the permanent storage layer, not a stepping
stone to Drive. The plan below covers Phase 1 → 1.5 → 1.6 as the complete product.

---

## 2. Complete Step-by-Step Build Plan

### PHASE 1 — Foundation (Steps 7–11)

---

#### Step 7 — Typed SSE Events `[CURRENT]`

**Goal:** SSE wire format becomes structured JSON. Every event type defined upfront.

**Files to create/update:**
- `backend/app/events.py` — create with all builder functions
- `backend/app/routes/chat.py` — use `events.token_event()` / `events.done_event()`
- `frontend/src/api/client.ts` — dispatch by `type` field in `streamChat`

**`events.py` full contract:**
```python
def token_event(delta: str) -> str
def done_event(via_provider: str = "", via_endpoint_id: str = "") -> str
def error_event(message: str) -> str
def provider_switch_event(from_provider: str, to_provider: str) -> str
def step_event(label: str, detail: str = "") -> str
def memory_hit_event(summary: str) -> str
def model_call_event(model: str, purpose: str) -> str
```

**`streamChat` TypeScript callback shape (wire now, consume progressively):**
```typescript
onToken(delta: string): void
onStep(label: string, detail: string): void
onMemoryHit(summary: string): void
onModelCall(model: string, purpose: string): void
onProviderSwitch(from: string, to: string): void
onDone(viaProvider: string): void
onError(message: string): void
```

**Also add:** `X-Accel-Buffering: no` to the chat route `StreamingResponse` headers.

**Done when:** Network tab shows `{"type": "token", "delta": "..."}` objects.

---

#### Step 8 — Conversation History

**Goal:** AI remembers the full conversation.
**Demo:** say "my name is Priya" → later ask "what's my name?" → it knows.

Frontend sends the full message array on every request. Backend forwards it to the provider.
No backend changes — backend becomes source of truth in Step 12.

**Done when:** multi-turn context works reliably.

---

#### Step 9 — Multi-Provider + normalize.py `[CHANGED: add Groq]`

**Goal:** add Cerebras + Groq. Lock in URL-routing normalize shape.

**New secrets to create:**
```
secrets/cerebras_api_key
secrets/cerebras_api_key.example
secrets/groq_api_key          ← NEW
secrets/groq_api_key.example  ← NEW
```

**`config.py` addition:**
```python
GROQ_API_KEY = read_secret("groq_api_key")
```

**`core/normalize.py` PROVIDERS map:**
```python
PROVIDERS = {
    "groq": {
        "url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "key": lambda: GROQ_API_KEY,
    },
    "cerebras": {
        "url": "https://api.cerebras.ai/v1",
        "model": "llama-3.3-70b",
        "key": lambda: CEREBRAS_API_KEY,
    },
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.5-flash",
        "key": lambda: GEMINI_API_KEY,
    },
}
```

**Done when:** Groq, Cerebras, and Gemini all stream real replies.

---

#### Step 10 — Model Switcher UI

**Goal:** dropdown lets the user pick which model answers.
**Demo:** switch from Groq to Gemini mid-conversation — context intact.

Hardcoded list for now (replaced by registry in Step R4):
```typescript
const MODELS = [
  { id: "groq",     label: "Llama 3.3 70B — Groq (fastest)", level: "fast" },
  { id: "cerebras", label: "Llama 3.3 70B — Cerebras (fast)", level: "fast" },
  { id: "gemini",   label: "Gemini 2.5 Flash — Google",       level: "balanced" },
]
```

**Done when:** switching provider mid-conversation preserves history.

---

#### Step 11 — Basic RAG (whole-doc injection) `[CHANGED: pdfplumber]`

**Goal:** user uploads text/PDF; content injected as context.

**`requirements.txt`:** replace `pypdf` with `pdfplumber`

**Backend:**
- `app/routes/upload.py` — `POST /upload` → extract text → store in `app/storage/documents.py`
- `app/storage/documents.py` — in-memory dict: `doc_id → text`
- `routes/chat.py` — if `doc_id` in request, prepend doc as system message

**Frontend:**
- 📎 button in `MessageInput.tsx`
- `uploadDoc(file: File) → string` in `client.ts`
- Attached doc chip with X to remove

**Done when:** upload a doc, ask about it — AI answers from the doc.

---

### PHASE 1.5 — Memory & Agent (Steps 12–16)

---

#### Step 12 — Multi-Chat Persistence

**Goal:** backend becomes source of truth; multiple named conversations persist.

**Data layout:**
```
data/conversations/<uuid>/
  meta.json         ← title, created_at, updated_at, model_id, message_count
  messages.jsonl    ← append-only; one JSON per line
  summary.md        ← added in Step 14
```

**Backend:**
- `app/storage/conversations.py` — full CRUD: create, list, get, delete, append_message, update_title, load_messages
- `app/routes/conversations.py` — REST: GET/POST/DELETE/PATCH /conversations[/{id}]
- `chat.py` update — accepts `conversation_id`; loads history from disk; appends after streaming

**Auto-title:** `BackgroundTask` on first message → fastest model → writes to `meta.json`

**Frontend:**
- `Sidebar.tsx` — conversation list; new/switch/delete
- `conversationId` in `App.tsx` state; sent with every request

**Done when:** two independent chats survive container restarts.

---

#### Step 13 — Complete Typed SSE Events

**Goal:** all event types dispatched end-to-end; frontend routes every type.

Already defined in Step 7. This step wires remaining silent callbacks:
- `onProviderSwitch` → inserts inline notice (rendered in Step R4)
- `onStep` → feeds trace panel (Step 16)
- `onMemoryHit` → feeds trace panel (Step 15)
- `onModelCall` → feeds trace panel (Step 16)

**Done when:** all 7 event types visible in Network tab.

---

#### Step 14 — Per-Chat Memory Summaries

**Goal:** rolling `summary.md` per conversation; long conversations stay coherent.

**Strategy:**
- Keep last 10 raw messages + `summary.md` as system message in every request
- Trigger summarisation in `BackgroundTask` every 20 messages
- `app/memory/summarize.py` → calls `normalize.chat_stream` with `fast` capability model

**Done when:** 30-message chat stays coherent; `summary.md` written to disk.

---

#### Step 15 — RAG over Memory `[CHANGED: sqlite-vec hybrid]`

**Goal:** relevant past-chat summaries retrieved and injected as context.

**New files:**
- `app/memory/embed.py` — `embed(text) → list[float]` via `text-embedding-004`
- `app/memory/index.py` — creates `data/memory/memory.db`; `add_chunk(conv_id, text)`
- `app/memory/retrieve.py` — hybrid vec + FTS search with RRF merge; `retrieve(query, top_k)`

**`chat.py` integration:**
```python
hits = await retrieve(user_message, top_k=3)
for hit in hits:
    yield memory_hit_event(hit["text"])
full_messages = [{"role": "system", "content": build_memory_context(hits)}] + messages
```

Called from `summarize.py` after finalisation: `add_chunk(conv_id, summary_text)`

**New requirement:** `sqlite-vec>=0.1.0`, `numpy`

**Done when:** fact stated in chat A surfaces in chat B automatically.

---

#### Step 16 — LangGraph Agent `[CHANGED: astream_events]`

**Goal:** multi-step agent: plan → retrieve → draft → critique → synthesise.

**New requirements:** `langgraph>=0.3.0`, `langchain-core`, `langgraph-checkpoint-sqlite>=3.0.1`

**Checkpointer setup (in `initialize_managers()`):**
```python
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

checkpointer = await AsyncSqliteSaver.from_conn_string(str(CHECKPOINTS_DB))
graph = build_agent_graph(resolver, rate_limiter).compile(checkpointer=checkpointer)
```

**Graph — 5 nodes (structure unchanged):**
```
load_context → agent → [search_memory | ask_model | final]
                ↑______________|___________|
```

**Streaming via `astream_events v2`:**
```python
async for event in graph.astream_events(
    {"conversation_id": conv_id, "history": messages, "user_model_id": model_id},
    config={"configurable": {"thread_id": conv_id}},
    version="v2",
):
    kind = event["event"]
    if kind == "on_chat_model_stream":
        yield token_event(event["data"]["chunk"].content)
    elif kind == "on_chain_start" and event.get("name") in TRACE_NODES:
        yield step_event(TRACE_NODES[event["name"]])
```

**Frontend — `TracePanel.tsx`:**
- Collapsible panel below each message bubble
- `step` events → labelled rows
- `memory_hit` events → faded rows
- `model_call` events → model badge rows
- Collapses on `done`; user can re-expand

**Invariants (unchanged):**
- Hard cap: 8 iterations max
- User's selected model always writes the final answer
- All LLM calls go through `normalize.chat_stream` — never `llm_core` directly

**Done when:** complex question → live trace → streaming answer.

---

### PHASE 1.6 — Rate-Limit Resilience (Steps R1–R4)

---

#### Step R1 — Registry Foundation

**Goal:** models and endpoints as data (JSON), not hardcoded Python/TS.

**Updated `endpoints.json` seed — adds Groq at priority 1:**
```json
[
  {
    "id": "ep-llama-3.3-70b-groq",
    "model_id": "llama-3.3-70b",
    "provider": "groq",
    "base_url": "https://api.groq.com/openai/v1",
    "provider_model_id": "llama-3.3-70b-versatile",
    "secret": "groq_api_key",
    "rpm_limit": 30,
    "rpd_limit": 1000,
    "tpm_limit": 12000,
    "priority": 1,
    "active": true
  },
  {
    "id": "ep-llama-3.3-70b-cerebras",
    "model_id": "llama-3.3-70b",
    "provider": "cerebras",
    "base_url": "https://api.cerebras.ai/v1",
    "provider_model_id": "llama-3.3-70b",
    "secret": "cerebras_api_key",
    "rpm_limit": 30,
    "rpd_limit": null,
    "tpm_limit": null,
    "priority": 2,
    "active": true
  }
]
```
*(Gemini, HuggingFace, GitHub, OpenRouter entries follow same shape with their priority/limits.)*

**New files:**
- `app/registry/schemas.py` — Pydantic `ModelEntry`, `EndpointEntry`
- `app/registry/seed.py` — writes JSON if absent
- `app/registry/loader.py` — `Registry` class with `get_model`, `endpoints_for`, `user_models`
- `app/routes/registry.py` — `GET /registry/models`
- `app/app_initializer.py` — `initialize_managers() → dict`

**Done when:** `GET /registry/models` returns the full catalog.

---

#### Step R2 — Rate Limiter

**Goal:** in-memory usage tracking, rolling windows, 90% threshold, cooldowns.

File: `app/core/rate_limiter.py` — `EndpointRateLimiter` class.
Full implementation specified in `plan/06-phase1.6-rate-limit.md` (unchanged).

**Done when:** unit tests show endpoint flips unavailable at ≥90% and recovers.

---

#### Step R3 — Resolver + normalize Contract Change

**Goal:** `normalize.chat_stream` takes `model_id` only; resolver handles endpoint selection.

**normalize.py new signature:**
```python
async def chat_stream(
    model_id: str,
    messages: list,
    resolver: Resolver,
    rate_limiter: EndpointRateLimiter,
    on_provider_switch: Callable | None = None,
) -> AsyncGenerator[str, None]
```

**`ChatRequest` simplification:**
```python
class ChatRequest(BaseModel):
    model_id: str
    conversation_id: str | None = None
    doc_id: str | None = None
```

**Agent routing:** `PURPOSE_TO_LEVEL` map → `resolver.pick_by_capability(level)`.

**Done when:** force priority-1 past 90% → reply from next endpoint; `provider_switch` event emitted.

---

#### Step R4 — Frontend Wiring

**Goal:** model dropdown from API; failover visible to user.

- `ModelSwitcher` fetches `GET /registry/models`; groups by Fast / Balanced / Research
- `onProviderSwitch` → inline notice between conversation turns
- `done.via_provider` → provider badge on assistant message bubbles

**Done when:** dropdown shows groups from API; failover notice appears; provider badge renders.

---

#### Merge Gate: Phase 1.6 → main

After R4 passes all tests → merge feature branch → tag release.

---

## 3. Build Order (Locked)

```
Phase 1:   Steps  7 → 8 → 9 → 10 → 11
Phase 1.5: Steps 12 → 13 → 14 → 15 → 16
Phase 1.6: Steps R1 → R2 → R3 → R4 → merge
```

One step per session. Demo works before moving on.

---

## 4. Requirements — Final Target State

### `backend/requirements.txt`

```
fastapi
uvicorn[standard]
pydantic>=2.0
httpx2
pytest
pytest-asyncio
langgraph>=0.3.0
langchain-core
langgraph-checkpoint-sqlite>=3.0.1
sqlite-vec>=0.1.0
pdfplumber
numpy
```

### `frontend/package.json` — additions

```json
"react-markdown": "^9.0.0"
```

---

## 5. Secrets — Final List

| File | Provider | Step Added |
|---|---|---|
| `secrets/gemini_api_key` | Google (Gemini) | Step 2.5 ✅ |
| `secrets/cerebras_api_key` | Cerebras | Step 9 |
| `secrets/groq_api_key` | Groq ← NEW | Step 9 |
| `secrets/huggingface_api_key` | HuggingFace | Step R1 |
| `secrets/github_api_key` | GitHub Models | Step R1 |
| `secrets/openrouter_api_key` | OpenRouter | Step R1 |

---

## 6. `constants.py` — Target State

```python
DATA_DIR          = Path(os.getenv("PAWN_DATA_DIR", "/app/data"))

REGISTRY_DIR      = DATA_DIR / "registry"
MODELS_FILE       = REGISTRY_DIR / "models.json"
ENDPOINTS_FILE    = REGISTRY_DIR / "endpoints.json"

CONVERSATIONS_DIR = DATA_DIR / "conversations"

MEMORY_DIR        = DATA_DIR / "memory"
MEMORY_DB         = MEMORY_DIR / "memory.db"       # ← NEW (replaces index.json)

CHECKPOINTS_DB    = DATA_DIR / "checkpoints.db"    # ← NEW (LangGraph SQLite checkpointer)

RATE_LIMITS_DIR   = DATA_DIR / "rate_limits"
SESSION_FILE      = RATE_LIMITS_DIR / "session.json"
```

---

## 7. Definition of Done — Single-User Local Edition

A fully working personal AI workspace where:

1. **Multi-provider streaming chat** — Groq → Cerebras → Gemini → HuggingFace → GitHub → OpenRouter (priority order)
2. **Automatic rate-limit failover** — proactive at 90% + reactive on live 429; `provider_switch` inline notice
3. **Conversation persistence** — local `data/conversations/`; survives container restarts
4. **Rolling memory summaries** — per-conversation compression; cross-conversation RAG retrieval
5. **Hybrid RAG** — sqlite-vec + FTS5; relevant past-chat context injected automatically
6. **LangGraph agent** — multi-step plan/retrieve/draft/critique/synthesise; trace panel in UI
7. **Model switcher** — API-driven dropdown grouped by capability level
8. **Document upload** — PDF/text injection into context window
9. **Streaming markdown rendering** — buffered `react-markdown` (no raw `**text**`)
10. **Typed SSE events** — all 7 types defined, dispatched, and handled end-to-end

All of the above runs locally via `docker compose up`. No cloud storage. No auth. No Google Drive.

---

## 8. Explicitly Deferred

| Feature | Reason |
|---|---|
| Phase 2: Google Drive | User constraint: local-only |
| Phase 3: Encryption | Only relevant with cloud storage |
| Phase 4: Multi-user / Auth | User constraint: single-user |
| NVIDIA NIM / Cloudflare Workers AI | Diminishing returns at 6 providers |
| Local Ollama embeddings (default) | `text-embedding-004` is default; Ollama documented as option |
| Streamdown (streaming markdown lib) | `react-markdown` + buffering achieves the same with less dependencies |

---

## 9. Open Questions

> **Groq API key** — Groq is now priority-1 (fastest free provider, 800+ tok/s LPU hardware).
> Get a free key at https://console.groq.com before Step 9.

> **Embedding model** — default is `text-embedding-004` (Gemini API, free, no local setup).
> If you prefer fully offline RAG (no API call for embeddings), switch to `nomic-embed-text`
> via local Ollama. Both produce 768-dim vectors; the interface is swappable without
> re-indexing. Decide before Step 15.
