# Phase 1 — Foundation
## Steps 1–11: Repo, Docker, Chat UI, Streaming, Multi-Model, Basic RAG

---

## Goal

A working local chat app: React frontend, FastAPI backend, two live providers streaming
real AI replies, model switcher, conversation history, and basic document upload.
No auth. No cloud. No persistence beyond the browser session.

At the end of Phase 1, the app is a fully functional single-session chat interface.

---

## Step 1 — Create the Repo

**Goal:** clean starting point, `.gitignore` done right from the first commit.
**Demo:** `git log` shows one commit; `secrets/` is tracked but `.gitkeep` only.

Directory structure to create manually:

```
pawn/
├── .claude/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── constants.py
│   │   ├── routes/
│   │   └── core/
│   └── tests/
├── frontend/
│   └── src/
├── secrets/
│   └── .gitkeep
├── workspace/
│   └── dev-log.md
├── docker-compose.yml
└── .gitignore
```

**.gitignore:**

```gitignore
# secrets — never commit real key files
secrets/*
!secrets/.gitkeep
!secrets/*.example

# data — personal conversation and memory files
data/

# python
__pycache__/
*.py[cod]
.venv/
venv/

# node
node_modules/
dist/
.vite/

# claude local settings
.claude/settings.local.json

# os
.DS_Store
Thumbs.db
```

Also create **`.dockerignore`** in the repo root (keeps build contexts lean):

```dockerignore
# secrets — never in Docker build context
secrets/*
!secrets/.gitkeep
!secrets/*.example

# data — personal files; mounted as a volume, not copied
data/

# python
__pycache__/
*.py[cod]
.venv/
venv/
*.egg-info/

# node
node_modules/
dist/
.vite/
*.log

# dev tools
.claude/
.git/
workspace/

# os
.DS_Store
Thumbs.db
```

Commit: `chore: init repo`

---

## Step 2 — Claude Code Config

**Goal:** `.claude/` wired so Claude Code is smart about this project.
**Demo:** `claude` in the repo; rules and agents load; hook blocks secret touches.

### .claude/CLAUDE.md

```markdown
# PAWN — Personal AI Workspace

Multi-model BYOK chat app. One interface, multiple AI providers, transparent rate-limit
failover, persistent memory on Google Drive.

## Stack
- Frontend: React + Vite + TypeScript + Tailwind v4
- Backend: FastAPI (Python 3.12), streaming via SSE
- Providers: URL-routed via _detect_provider(url) in core/llm_core.py
- Runtime: Docker + docker-compose

## Hard Rules
- Never log or hardcode API keys.
- Secrets are read from /run/secrets/* via app/config.py only.
- All LLM calls go through app/core/normalize.py → llm_core.py. Never inline.
- Frontend and backend communicate via REST + SSE only. No shared code.
- One test per new endpoint. Tests must pass before a step is marked done.
- Update workspace/dev-log.md at the end of each step.
```

### .claude/rules/backend.md

```markdown
# Backend Rules
- Python 3.12, FastAPI, async everywhere.
- Pydantic v2 for all request/response models.
- Streaming via Server-Sent Events (text/event-stream).
- All LLM calls go through app/core/normalize.py only — never direct provider calls in routes.
- Secrets from /run/secrets/* via app/config.py. Never inline keys. Never .env.
- Docker is the canonical runtime. docker compose up is how you start it.
- pytest for all tests. One test file per route module.
```

### .claude/rules/frontend.md

```markdown
# Frontend Rules
- React + Vite + TypeScript + Tailwind v4 only. No extra UI libraries without explicit approval.
- All API/SSE calls go through src/api/client.ts. No inline fetch in components.
- Components stay small and single-purpose.
- Types in src/types.ts for shared interfaces.
```

### .claude/settings.json (Windows / PowerShell hook)

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "powershell -NoProfile -Command \"$p=$input|Out-String|ConvertFrom-Json; if($p.tool_input.command -match 'secrets/[^.\\n]*[\\r\\n]|\\.env[^.]|git +push +.*--force'){Write-Error 'BLOCKED: touches secrets or force-push'; exit 2} else {exit 0}\""
          }
        ]
      }
    ]
  }
}
```

Commit: `chore: claude code config — rules, agents, skills`

---

## Step 2.5 — Docker Scaffolding

**Goal:** secrets-as-files pattern locked in from the start. API keys never touch env vars.
**Demo:** `docker compose config` validates; secret files mounted at `/run/secrets/*`.

### constants.py

```python
# backend/app/constants.py
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
```

### config.py

```python
# backend/app/config.py
import os
from pathlib import Path

def read_secret(name: str) -> str | None:
    path = Path(f"/run/secrets/{name}")
    if path.exists():
        return path.read_text().strip()
    return os.getenv(name.upper())

GEMINI_API_KEY      = read_secret("gemini_api_key")
CEREBRAS_API_KEY    = read_secret("cerebras_api_key")
HUGGINGFACE_API_KEY = read_secret("huggingface_api_key")
GITHUB_API_KEY      = read_secret("github_api_key")
OPENROUTER_API_KEY  = read_secret("openrouter_api_key")
```

### docker-compose.yml

```yaml
services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    secrets:
      - gemini_api_key
      - cerebras_api_key
      - huggingface_api_key
      - github_api_key
      - openrouter_api_key
    volumes:
      - ./backend:/app
      - ./backend/data:/app/data
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

  frontend:
    build: ./frontend
    ports:
      - "5173:5173"
    environment:
      - VITE_API_URL=http://localhost:8000
    volumes:
      - ./frontend:/app
      - /app/node_modules
    command: npm run dev -- --host

secrets:
  gemini_api_key:
    file: ./secrets/gemini_api_key
  cerebras_api_key:
    file: ./secrets/cerebras_api_key
  huggingface_api_key:
    file: ./secrets/huggingface_api_key
  github_api_key:
    file: ./secrets/github_api_key
  openrouter_api_key:
    file: ./secrets/openrouter_api_key
```

Create example files and empty placeholder files for unused keys (required for compose config to validate).

Commit: `chore: docker scaffolding — compose, secrets-as-files, constants, config loader`

---

## Step 3 — Chat UI

**Goal:** working chat interface in the browser. Static, no backend yet.
**Demo:** type a message; it appears as a chat bubble.

Scaffold frontend:
```bash
cd frontend
npm create vite@latest . -- --template react-ts
npm install
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
```

Components to build:
- `src/components/ChatWindow.tsx` — scrollable message list, auto-scrolls to bottom
- `src/components/MessageInput.tsx` — textarea + send button; Enter sends, Shift+Enter newline
- `src/components/Message.tsx` — single bubble: user (right, dark) vs assistant (left, light)
- `src/types.ts` — `Message { role, content, id }`, `ChatState`
- `src/App.tsx` — wires components with local state; no API calls yet

No API calls. Messages echo locally. Get layout, spacing, and scroll behaviour right first.

Commit: `feat: static chat UI — message list, input, bubbles`

---

## Step 4 — FastAPI Backend

**Goal:** running backend container with health check and middleware foundation.
**Demo:** `curl http://localhost:8000/health` returns `{"status": "ok"}`

`backend/requirements.txt`:
```
fastapi
uvicorn[standard]
pydantic
httpx
pytest
httpx  # for TestClient
```

`backend/app/main.py`:
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from app.middleware.security import SecurityHeadersMiddleware
from app.middleware.timeout import RequestTimeoutMiddleware

app = FastAPI()

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(RequestTimeoutMiddleware, timeout=45, sse_paths=["/chat"])
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])

@app.get("/health")
async def health():
    return {"status": "ok"}
```

Build middleware:
- `app/middleware/security.py` — adds CSP, X-Frame-Options, Referrer-Policy headers
- `app/middleware/timeout.py` — 45s timeout; excludes SSE paths from timeout

Commit: `feat: fastapi backend — health check, middleware stack`

---

## Step 5 — Connect Frontend to Backend

**Goal:** frontend calls backend on load; connection confirmed.
**Demo:** browser console logs `{status: ok}` from the live backend.

`frontend/src/api/client.ts`:
```typescript
const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export async function healthCheck(): Promise<{ status: string }> {
  const res = await fetch(`${BASE_URL}/health`);
  return res.json();
}
```

`frontend/.env.example`:
```
VITE_API_URL=http://localhost:8000
```

Call from `App.tsx` `useEffect` on mount. Log result. Connection established.

Commit: `feat: frontend api client + health check wired`

---

## Step 6 — First Real AI Response (Gemini)

**Goal:** send a message to a real provider, get a real reply.
**Demo:** type "hello", get a real reply from Gemini 2.5 Flash.

This step wires the first end-to-end path: UI → backend → provider → response.
Uses the URL-routing pattern from the start — no legacy normalize shape.

Add to requirements.txt: `httpx` (already there)

`backend/app/core/llm_core.py` (minimal version for this step):
```python
import httpx
from app.exceptions import ProviderError

_client: httpx.AsyncClient | None = None

def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
    return _client

async def stream_llm(url: str, model: str, messages: list, headers: dict):
    payload = {"model": model, "messages": messages, "stream": True}
    async with _get_client().stream("POST", f"{url}/chat/completions", json=payload, headers=headers) as resp:
        if resp.status_code >= 400:
            raise ProviderError(kind="upstream_error", message=f"HTTP {resp.status_code}")
        async for line in resp.aiter_lines():
            if line.startswith("data: ") and not line.endswith("[DONE]"):
                # parse SSE delta
                ...
                yield token
```

`backend/app/routes/chat.py`:
```python
from fastapi import APIRouter
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from app.core import llm_core
from app.config import GEMINI_API_KEY

router = APIRouter()

class ChatRequest(BaseModel):
    messages: list[dict]

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
GEMINI_MODEL = "gemini-2.5-flash-preview-05-20"

@router.post("/chat")
async def chat(req: ChatRequest):
    headers = {"Authorization": f"Bearer {GEMINI_API_KEY}"}
    async def generate():
        async for token in llm_core.stream_llm(GEMINI_URL, GEMINI_MODEL, req.messages, headers):
            yield f"data: {token}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")
```

Register router in `main.py`. Update `App.tsx` to call `/chat` and render the reply.

Commit: `feat: gemini via openai-compat endpoint + /chat SSE route`

---

## Step 7 — Typed SSE Events (wire format)

**Goal:** SSE stream uses structured events, not raw token strings. Infrastructure for
the agent steps later. UI looks identical — wire format is richer.
**Demo:** in Network tab, stream shows `{"type": "token", "delta": "..."}` objects.

`backend/app/events.py`:
```python
import json

def token_event(delta: str) -> str:
    return f"data: {json.dumps({'type': 'token', 'delta': delta})}\n\n"

def done_event(via_provider: str = "", via_endpoint_id: str = "") -> str:
    return f"data: {json.dumps({'type': 'done', 'via_provider': via_provider, 'via_endpoint_id': via_endpoint_id})}\n\n"

def error_event(message: str) -> str:
    return f"data: {json.dumps({'type': 'error', 'message': message})}\n\n"

def provider_switch_event(from_provider: str, to_provider: str) -> str:
    return f"data: {json.dumps({'type': 'provider_switch', 'from': from_provider, 'to': to_provider})}\n\n"

def step_event(label: str, detail: str = "") -> str:
    return f"data: {json.dumps({'type': 'step', 'label': label, 'detail': detail})}\n\n"

def memory_hit_event(summary: str) -> str:
    return f"data: {json.dumps({'type': 'memory_hit', 'summary': summary})}\n\n"

def model_call_event(model: str, purpose: str) -> str:
    return f"data: {json.dumps({'type': 'model_call', 'model': model, 'purpose': purpose})}\n\n"
```

Update the route to use `events.token_event()` / `events.done_event()`. Update `client.ts`
to parse `type` field and dispatch to `onToken` / `onDone` / `onError` callbacks.
Other event types are wired but show nothing in the UI yet.

Full SSE protocol reference: see `plan/11-sse-protocol.md`.

Commit: `feat: typed SSE events — structured wire format`

---

## Step 8 — Conversation History

**Goal:** AI remembers the whole conversation, not just the last message.
**Demo:** say "my name is Priya", then ask "what's my name?" — it knows.

Frontend sends the full message array on every request. Backend forwards it to the provider.
No backend change needed yet (backend becomes source of truth in Step 12).

`client.ts` `streamChat(messages: Message[])` sends:
```json
{
  "messages": [
    {"role": "user", "content": "my name is Priya"},
    {"role": "assistant", "content": "Nice to meet you Priya!"},
    {"role": "user", "content": "what is my name?"}
  ]
}
```

Commit: `feat: full conversation history forwarded per request`

---

## Step 9 — Multi-Provider (add Cerebras + URL routing)

**Goal:** add Cerebras as a second provider. Move to the final URL-routing shape.
**Demo:** both Gemini and Cerebras stream real replies; switching between them works.

This step introduces the full `normalize.py` public API and the `_detect_provider` shape.
Even without the resolver yet, the URL-routing pattern is locked in from this step.

`backend/app/core/normalize.py`:
```python
from app.core.llm_core import stream_llm, _detect_provider, _provider_headers
from app.config import GEMINI_API_KEY, CEREBRAS_API_KEY
from app.exceptions import ProviderError

PROVIDERS = {
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.5-flash-preview-05-20",
        "key": lambda: GEMINI_API_KEY,
    },
    "cerebras": {
        "url": "https://api.cerebras.ai/v1",
        "model": "llama-3.3-70b",
        "key": lambda: CEREBRAS_API_KEY,
    },
}

async def chat_stream(provider_key: str, messages: list, model: str | None = None):
    cfg = PROVIDERS.get(provider_key)
    if not cfg:
        raise ProviderError(kind="unknown_provider", message=f"Unknown provider: {provider_key}")
    url = cfg["url"]
    mdl = model or cfg["model"]
    api_key = cfg["key"]()
    detected = _detect_provider(url)
    headers = _provider_headers(detected, api_key, url)
    async for token in stream_llm(url, mdl, messages, headers):
        yield token
```

Update `ChatRequest` to include `provider: str` and optional `model: str`. Update the
frontend model switcher with a hardcoded list of providers/models for now (replaced by the
registry in Step R4). The provider list is a static TypeScript array for Steps 9–R3.

Commit: `feat: cerebras provider + url-routing normalize shape`

---

## Step 10 — Model Switcher UI

**Goal:** dropdown lets the user pick which model answers the next message.
**Demo:** switch from Gemini to Cerebras mid-conversation — context stays intact.

`frontend/src/components/ModelSwitcher.tsx`:
- Hardcoded list of `{ provider, model, label, description }` for now
- Selected value stored in `App.tsx` state and sent with every request
- Context (message array) is untouched when switching — same history, different brain

This is the "one context, multiple brains" feature. When it works, Phase 1 MVP is complete.

Commit: `feat: model switcher — provider/model selectable per message`

---

## Step 11 — Basic RAG (whole-doc injection)

**Goal:** user uploads a text/PDF doc; its content is injected as context.
**Demo:** upload a document, ask "summarise this" — AI answers from the doc.

Add to requirements.txt: `pypdf`

Backend:
- `app/routes/upload.py` — `POST /upload`: accept file, store content in `app/storage/documents.py`
  (in-memory dict: `doc_id → text`), return `{ "doc_id": "..." }`.
- `app/storage/documents.py` — thin in-memory store. Single dict, no file I/O yet.
- `routes/chat.py` — if `doc_id` is present in `ChatRequest`, prepend doc text as system message.

Frontend:
- 📎 button in `MessageInput.tsx` triggers file picker
- `api/client.ts` exports `uploadDoc(file: File) → string` (returns doc_id)
- `doc_id` stored in state, sent with every subsequent chat request
- Chip showing attached doc name; X to remove

No embeddings yet. Whole-doc injection into the context window.
Step 15 adds chunking and cosine retrieval.

Commit: `feat: basic RAG — whole-doc injection into context`

---

## Phase 1 Completion Checklist

- [ ] `docker compose up` starts both services
- [ ] Health check returns 200
- [ ] Gemini streams real replies
- [ ] Cerebras streams real replies
- [ ] Context is preserved across messages
- [ ] Switching provider mid-conversation preserves history
- [ ] File upload returns a doc_id
- [ ] AI answers questions about the uploaded doc
- [ ] All backend tests pass
- [ ] Frontend builds without errors
- [ ] `dev-log.md` has a dated entry for each step

---

## Working Agreement (Phase 1)

- One step per session. Pause for review before moving to the next.
- Review every diff. Understand every line.
- Tests present and passing before a step is marked done.
- Dated entry in `workspace/dev-log.md` at the end of each step.
