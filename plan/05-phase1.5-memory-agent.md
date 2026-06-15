# Phase 1.5 — Memory & Agent
## Steps 12–16: Persistence, Typed SSE, Summaries, RAG, LangGraph

---

## Goal

Turn the app from a stateless proxy into a stateful, memory-augmented agent.

The single most important shift: **the backend becomes the source of truth**. The frontend
stops owning the conversation array. It sends `conversation_id + new message` and renders
a live stream of typed events.

At the end of Phase 1.5, the app:
- Persists multiple named conversations across reloads
- Generates and manages rolling conversation summaries
- Retrieves relevant past-chat context automatically (cross-conversation RAG)
- Runs a multi-step LangGraph agent with visible steps in the UI

---

## Architecture Decisions (Locked Before Starting)

| Decision | Choice |
|---|---|
| Storage | `data/` at repo root (gitignored). Files only — no DB until needed. |
| SSE events | Typed, not just deltas: `token`, `step`, `memory_hit`, `model_call`, `provider_switch`, `done`, `error` |
| Orchestration | LangGraph (`StateGraph`). Nodes call `normalize.chat_stream` — provider isolation rule preserved |
| Tool protocol | JSON/ReAct inside the agent node. Model-agnostic, works across all providers |
| Embeddings | `text-embedding-004` (Gemini embedding API) behind a swappable `embed.py` interface |
| Summary model | Routed via `normalize` to best available `fast`-tier model (e.g. Gemini 2.5 Flash Lite) |
| RAG | Brute-force cosine over `data/memory/index.json`. No vector DB |
| Final answer | Always written by the user's selected brain. Agent never overrides this |

---

## Model Roles (Three Distinct Jobs)

| Job | Model | Rate limit (free) | User-facing? |
|---|---|---|---|
| **Chat brain** — answers the user including RAG-informed answers | User's selected model (Gemini 2.5 Flash, Llama 3.3 70B, etc.) | Varies per model | ✅ in the dropdown |
| **Embedder** — turns text into vectors for retrieval | `text-embedding-004` | 1,500 req/min | ❌ internal only |
| **Fast internal model** — summaries, auto-titles, agent plan/draft | Best available `fast` capability-level model (e.g. Gemini 2.5 Flash Lite) | Varies | ❌ not overriding user choice |

All providers use the OAI-compatible REST endpoint — there is no separate WebSocket-based
internal provider. The agent routes internal tasks by capability level (`fast`, `balanced`,
`research`) and the resolver picks the best available endpoint automatically.

The flow when memory is involved:
```
Fast model writes summaries
  → text-embedding-004 embeds them into index.json
  → Retrieval pulls the relevant ones on new messages
  → User's selected brain composes the answer with those injected as context
```

"One context, multiple brains" stays intact.

---

## Step 12 — Multi-Chat Persistence

**Goal:** backend becomes source of truth; multiple named conversations, each persisting
across reloads.
**Demo:** open two chats, each holds separate history independently. Switch, delete, create.
Auto-title fires on the first message (visible in logs).

### Data Layout

```
data/conversations/
  <uuid>/
    meta.json         ← title, created_at, updated_at, model_id, message_count
    messages.jsonl    ← append-only; one JSON per line
```

**Docker volume:** `data/` is mounted into the backend container via `docker-compose.yml`:
```yaml
volumes:
  - ./backend/data:/app/data
```
Add `data/` to `.gitignore` (personal data, like `secrets/`). The volume keeps data alive
across container restarts without committing it to the repo.

Add `data/` to `.gitignore`.

### Backend

**`app/storage/conversations.py`** — all file I/O for conversations:
```python
def create_conversation(model_id: str) -> str: ...           # writes meta.json, returns uuid
def list_conversations() -> list[ConversationMeta]: ...      # ordered by updated_at desc
def get_conversation(conv_id: str) -> ConversationDetail: ..  # meta + messages
def delete_conversation(conv_id: str) -> None: ...
def append_message(conv_id: str, role: str, content: str, **extra) -> None: ...
def update_title(conv_id: str, title: str) -> None: ...
def load_messages(conv_id: str) -> list[dict]: ...
```

**Routes** (`app/routes/conversations.py`):
- `GET  /conversations`          — list all
- `POST /conversations`          — create new
- `GET  /conversations/{id}`     — get with messages
- `DELETE /conversations/{id}`   — delete
- `PATCH /conversations/{id}`    — update title

**`/chat` route updated:**
- Accepts `conversation_id: str` in `ChatRequest`
- Loads history from `conversations.load_messages(conv_id)` — not from the request body
- Appends user message before calling provider
- Appends assistant reply to `messages.jsonl` after streaming completes (with `via_provider`, `via_endpoint_id`)

**Auto-title:**
- On first message in a conversation, fire a `BackgroundTask`
- Call `normalize.chat_stream("gemini-flash-live", [{"role": "user", "content": f"Give a 5-word title for this conversation: {first_message}"}])`
- Write result to `meta.json` via `update_title`

### Frontend

- `src/components/Sidebar.tsx` — conversation list; title + relative timestamp; new/switch/delete
- On app load: `GET /conversations`; if empty, auto-create one
- `conversationId` in `App.tsx` state; sent with every chat request
- `streamChat` sends `{ conversation_id, model_id, content }` — not the full message array

Tests: conversation CRUD (happy path + 404), chat with `conversation_id`, history loading.

Commit: `feat: multi-chat persistence — conversations stored to disk, backend is source of truth`

---

## Step 13 — Complete Typed SSE Events

**Goal:** all event types implemented end-to-end. Frontend routes every event type.
`provider_switch` is added here and will be used in Phase 1.6 when failover lands.
**Demo:** Network tab shows all event types. UI renders tokens as before. Other events
are wired in `streamChat` callbacks (used in Steps 14–16).

### Event Reference

```json
{ "type": "token",           "delta": "Hello" }
{ "type": "step",            "label": "Searching memory", "detail": "query: preferences" }
{ "type": "memory_hit",      "summary": "From chat 2026-06-07: user prefers concise answers" }
{ "type": "model_call",      "model": "gemini-flash-live", "purpose": "draft" }
{ "type": "provider_switch", "from": "huggingface", "to": "github" }
{ "type": "done",            "via_provider": "cerebras", "via_endpoint_id": "ep-llama-3.3-70b-cerebras" }
{ "type": "error",           "message": "Rate limit reached — try again shortly" }
```

### Backend

`app/events.py` (all builder functions, see `plan/11-sse-protocol.md` for full reference).
Route emits each event type at the appropriate point in the request lifecycle.

### Frontend

`api/client.ts` `streamChat` dispatches by `type`:
```typescript
onToken(delta: string): void        // append to message bubble
onStep(label: string, detail: string): void  // trace panel (Step 16)
onMemoryHit(summary: string): void  // trace panel (Step 15)
onModelCall(model: string, purpose: string): void  // trace panel (Step 16)
onProviderSwitch(from: string, to: string): void  // inline notice (Step R4)
onDone(viaProvider: string): void   // set provider badge on bubble
onError(message: string): void      // show error state
```

Other callbacks wired but silent until their steps land.

Commit: `feat: complete typed SSE event dispatch — frontend routes all event types`

---

## Step 14 — Per-Chat Memory Summaries

**Goal:** each chat generates a rolling summary for context compression and cross-chat
retrieval. Long conversations stay coherent without sending the full transcript.
**Demo:** 30-message conversation — AI still knows message 1. Confirm `summary.md` exists.

### Data Layout (extends Step 12)

```
data/conversations/<uuid>/
  meta.json
  messages.jsonl
  summary.md     ← rolling compressed memory; updated in-flight and on close
```

### Summarization Strategy

**Intra-chat context management:**
- Keep the last N raw messages (e.g. 10) + `summary.md` as a system message
- When `message_count` crosses a threshold (e.g. every 20 messages), trigger a background summarization pass
- Summarization prompt: "Extend this summary to include the new messages. Keep it concise."
- New summary written back to `summary.md`

**Finalization:**
- On conversation fetch after inactivity, or on explicit close, run a final pass
- Distills the whole transcript into a clean `summary.md` used for memory indexing (Step 15)

### Backend

**`app/storage/conversations.py`** (add):
```python
def load_summary(conv_id: str) -> str: ...   # returns "" if summary.md absent
def save_summary(conv_id: str, text: str) -> None: ...
```

**`app/memory/summarize.py`**:
```python
async def summarize_conversation(conv_id: str, normalize_fn) -> None:
    messages = load_messages(conv_id)
    current_summary = load_summary(conv_id)
    prompt = build_summarize_prompt(current_summary, messages)
    result = ""
    async for token in normalize_fn("gemini-flash-live", [{"role": "user", "content": prompt}]):
        result += token
    save_summary(conv_id, result.strip())
```

**`routes/chat.py`** (update):
```python
# Before calling provider:
summary = load_summary(conversation_id)
full_messages = build_context(summary, last_n_messages, new_user_message)

# After streaming completes, in BackgroundTask:
await summarize_conversation(conv_id, normalize.chat_stream)
```

Tests: summarize function (mocked normalize), context-window truncation logic.

Commit: `feat: per-chat rolling summaries — context compression + memory artifact`

---

## Step 15 — RAG Over Memory

**Goal:** retrieve relevant past-chat summaries and inject them as context.
The AI draws on knowledge from old conversations without those conversations being open.
**Demo:** in chat A, say "I prefer bullet-point answers". Close it. Open chat B, ask
something — AI references the preference from chat A.

### Data Layout (extends Step 14)

```
data/memory/
  index.json    ← chunks: { id, conv_id, text, embedding, created_at }
```

### Embedding Interface

`app/memory/embed.py`:
```python
async def embed(text: str) -> list[float]:
    # Implementation: Gemini text-embedding-004 via Google's OpenAI-compatible endpoint
    # Interface is swappable — local model (MiniLM) can replace this without touching callers
    ...
```

### Indexing

`app/memory/index.py`:
```python
async def add_chunk(conv_id: str, text: str) -> None:
    embedding = await embed(text)
    chunk = {
        "id": generate_id(),
        "conv_id": conv_id,
        "text": text,
        "embedding": embedding,
        "created_at": utcnow_iso(),
    }
    # append to index.json
```

Called from `summarize.py` after finalization.

### Retrieval

`app/memory/retrieve.py`:
```python
def cosine_similarity(a: list[float], b: list[float]) -> float:
    # numpy dot product / (norm_a * norm_b)
    ...

async def retrieve(query: str, top_k: int = 3) -> list[MemoryChunk]:
    query_embedding = await embed(query)
    chunks = load_index()   # load index.json into memory
    scored = [(chunk, cosine_similarity(query_embedding, chunk["embedding"])) for chunk in chunks]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [chunk for chunk, score in scored[:top_k]]
```

### Integration in Chat Route

```python
# routes/chat.py — before building context
hits = await retrieve(user_message, top_k=3)
for hit in hits:
    yield memory_hit_event(hit["text"])   # emits memory_hit SSE event
context_prefix = build_memory_context(hits)
full_messages = [{"role": "system", "content": context_prefix}] + conversation_messages
```

The user's selected brain still writes the answer — retrieval only injects context.

Add to requirements.txt: `numpy`

Tests: cosine similarity (no API), top-k retrieval (fixed embeddings), index roundtrip.

Commit: `feat: RAG over memory — past-chat retrieval injected as context`

---

## Step 16 — LangGraph Agent

**Goal:** replace single-shot `provider → stream` with a multi-step agent that can plan,
retrieve, draft, critique, and synthesize — with every step visible live in the UI.
Optimised for best outcomes, not speed.
**Demo:** ask a hard multi-part question. Watch trace panel show:
*Planning → Searching memory → Drafting → Critiquing → [streaming final answer]*

### Graph Structure

```
load_context
     ↓
 agent_node (decides next action via JSON/ReAct)
     ↓ action
   ┌──────────────────────────┐
   │  search_memory           │  → retrieve() → emit memory_hit events → loop back
   │  ask_model (draft/crit)  │  → normalize.chat_stream() → emit model_call + token events → loop back
   │  final                   │  → synthesize → stream answer to user → persist
   └──────────────────────────┘
```

Hard step cap: 8 iterations. After cap, force `final` action.

### LangGraph Setup

Add to requirements.txt: `langgraph`, `langchain-core`

`app/agent/graph.py`:
```python
from langgraph.graph import StateGraph
from typing import TypedDict

class AgentState(TypedDict):
    conversation_id: str
    history: list[dict]
    retrieved_memory: list[str]
    scratchpad: list[dict]
    next_action: dict | None
    final_answer: str | None
    step_count: int

# Nodes:
# load_context_node: loads conversation + retrieves memory
# agent_node: runs JSON/ReAct prompt, parses action
# search_memory_node: calls retrieve(), appends to scratchpad
# ask_model_node: calls normalize.chat_stream with purpose routing
# final_node: streams synthesized answer
```

All nodes call `normalize.chat_stream` — never `llm_core.stream_llm` directly.
Provider isolation rule preserved throughout.

### JSON/ReAct Protocol

Agent node builds a prompt with:
- Conversation history
- Retrieved memory
- Scratchpad (prior steps this turn)
- Available actions

Model responds with exactly one JSON action:
```json
{ "action": "search_memory", "query": "user project preferences" }
{ "action": "ask_model", "purpose": "draft", "prompt": "Write a first draft of..." }
{ "action": "ask_model", "purpose": "critique", "prompt": "Critique this draft: ..." }
{ "action": "final", "answer": "Based on my research..." }
```

`app/agent/parser.py`:
```python
def parse_action(output: str) -> dict:
    # Extract JSON from model output
    # Fallback: if no valid JSON found, return {"action": "final", "answer": output}
    ...
```

### Capability-Level Routing

`app/agent/routing.py`:
```python
PURPOSE_TO_LEVEL = {
    "plan":     "fast",      # cheapest available fast model
    "draft":    "balanced",  # best available balanced model
    "critique": "balanced",  # different provider, same level (resolver picks next)
    "research": "research",  # best available research model
    # "final": always the user's selected model — passed in per request, never routed here
}
```

The agent never names a provider. It requests a capability level. The resolver (Phase 1.6)
picks the best available endpoint. Before Phase 1.6 lands, this map routes to hardcoded
model IDs from the registry as a placeholder.

### Frontend — Trace Panel

`src/components/TracePanel.tsx`:
- Collapsible panel below the message bubble
- Renders live as step events arrive
- Each `step` event → row with label + optional detail
- Each `memory_hit` event → faded row with retrieved text snippet
- Each `model_call` event → row with model name + purpose badge
- Collapses by default once `done` fires; user can re-expand

Tests: graph node unit tests (mocked providers), parser (valid JSON, fallback), full graph
integration (mocked), step-cap enforcement.

Commit: `feat: LangGraph agent — multi-step plan/retrieve/draft/critique/synthesize`

---

## Phase 1.5 Completion Checklist

- [ ] Multiple named conversations persist across restarts
- [ ] New/switch/delete conversations work in sidebar
- [ ] Auto-title fires on first message
- [ ] All typed SSE events dispatched and parsed on frontend
- [ ] Rolling summaries generated at threshold and on close
- [ ] Memory index built from finalized summaries
- [ ] Memory retrieval returns relevant hits from past chats
- [ ] Agent trace panel shows live steps
- [ ] Final answer is always the user's selected model
- [ ] All backend tests pass
- [ ] `dev-log.md` updated per step
