# PAWN — Personal AI Workspace

Multi-model, multi-user BYOK AI chat application. One interface, multiple LLM providers, transparent rate-limit failover, persistent memory, LangGraph agent, and on-demand GPU image generation via Kaggle — all with user data stored on the user's own Google Drive.

Built solo. No starter templates, no AI backend services — auth, streaming, GPU orchestration, and storage implemented directly.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, Vite 8, TypeScript, Tailwind v4 |
| Routing | react-router-dom |
| Markdown | react-markdown |
| Backend | FastAPI (Python 3.12), Pydantic v2, fully async |
| Streaming | Server-Sent Events (SSE) via `StreamingResponse` |
| Auth | Google OAuth2 (confidential client), PyJWT (HS256, 7-day sessions) |
| Encryption | AES-256-GCM via Python `cryptography` (BYOK keys + Drive tokens at rest) |
| Agent | LangGraph `StateGraph` (5 nodes, `AsyncSqliteSaver` checkpointer) |
| Memory retrieval | Supabase pgvector + PostgreSQL FTS, RRF fusion |
| Text embeddings | Google `text-embedding-004` |
| Database | Supabase — pgvector, BYOK key store, image job queue |
| File storage | Google Drive API (per-user, `drive.file` scope) |
| Image generation | Kaggle Kernels API — SDXL + FLUX.1-schnell on T4 / dual-T4 GPU |
| Infrastructure | Docker, Docker Compose, secrets-as-files |
| Testing | pytest, httpx.AsyncClient, FastAPI TestClient |

---

## Architecture

### Multi-Provider LLM Routing

All LLM calls go through `backend/app/core/normalize.py` → `llm_core.py`. Routes and agents never call providers directly.

All 6 providers (Gemini, Groq, Cerebras, HuggingFace, GitHub Models, OpenRouter) use the OpenAI-compatible chat completions wire format. `llm_core.py` speaks one protocol; `normalize.py` swaps the base URL, auth header, and model name per provider. No provider SDKs — no vendor lock-in.

The model registry lives in `data/registry/models.json` and `endpoints.json` — JSON files, not code. Adding a provider means editing JSON.

**Rate-limit resilience (`backend/app/core/resolver.py`, `rate_limiter.py`):**
- `EndpointRateLimiter` tracks rolling RPM and TPM per endpoint.
- At 90% of a limit the endpoint is soft-blocked before a real 429 arrives.
- On a live 429 the endpoint enters a cooldown. After N consecutive failures it is marked dead-host.
- Cross-model fallback: if the selected model is rate-limited before the first token, `chat_stream` iterates `fallback_models` (same capability level, user-keyed) and switches transparently — emitting a `provider_switch` SSE event rendered as an inline notice in the chat.

**BYOK (Bring Your Own Key):**
- Users configure keys in Settings → API Keys. Keys are AES-256-GCM encrypted and stored in Supabase, scoped by `user_id`. Key values are never returned by any API endpoint.
- `resolver.pick(model_id, user_id)` resolves only endpoints the user holds a key for. No key → clear error: *"Add your provider key in Settings."*
- Keys are decrypted once per request window via a short-TTL cache (`core/key_store.py`).

---

### Streaming (SSE)

Backend: `StreamingResponse` with `text/event-stream`. Every response is a stream of **typed JSON events** — never raw strings.

7 event types defined in `backend/app/events.py`:

| Type | Carries |
|---|---|
| `token` | streaming text delta |
| `done` | stream end + provider name |
| `error` | sanitized error message + optional code |
| `provider_switch` | failover notice |
| `step` | LangGraph agent step |
| `memory_hit` | retrieved memory chunk |
| `model_call` | secondary model invocation |

`X-Accel-Buffering: no` and `Cache-Control: no-cache` headers prevent proxy buffering. The 45s timeout middleware exempts SSE paths.

Frontend (`frontend/src/api/client.ts`): `streamChat()` opens a `fetch` + `ReadableStream` + `TextDecoder` pipeline. Dispatches on `event.type` into a `StreamChatCallbacks` object. Components receive typed callbacks — they never parse raw SSE.

---

### LangGraph Agent

A 5-node `StateGraph` replaces a single LLM call: `load_context → agent → search_memory → ask_model → final`.

- **`agent` node**: parses a ReAct-style JSON action — decides whether to call `search_memory`, `ask_model`, or go to `final`.
- **`search_memory` node**: hybrid vector + FTS retrieval (see Memory section).
- **`ask_model` node**: secondary LLM call for a focused sub-question, routed by capability level.
- **`final` node**: synthesizes and streams the answer.
- **Checkpointer**: `AsyncSqliteSaver` persists state by `{user_id}:{conv_id}` thread ID — reasoning survives restarts.
- Custom events from nodes (`adispatch_custom_event`) flow into `astream_events` and are emitted as `step` / `memory_hit` / `model_call` SSE events, displayed in a collapsible inline trace panel per message.

---

### Memory and RAG

1. Every conversation that reaches a 20-turn threshold is summarized by the fastest available LLM in a background task → `summary.md` written to Google Drive.
2. Summaries are chunked, embedded via `text-embedding-004`, and stored in Supabase `memory_chunks` (pgvector).
3. On each request the `search_memory` node retrieves via:
   - **Vector search**: `match_memory_chunks` Supabase RPC (cosine similarity).
   - **Full-text search**: `search_memory_chunks` Supabase RPC (PostgreSQL FTS).
   - **RRF fusion**: both ranked lists merged in Python via Reciprocal Rank Fusion.
4. Retrieved chunks are injected as a system message; surfaced in the UI as `memory_hit` events.

All `memory_chunks` rows are scoped by `user_id`. Active conversation is excluded from retrieval to avoid circular recall.

**Graceful degradation**: Supabase down → `retrieve()` returns `[]`. Embedding fails (no BYOK Google key) → FTS-only. Agent still answers.

---

### Auth + Multi-User

**OAuth2 flow:**
- `GET /auth/login` → Google OAuth2 (confidential client, PKCE disabled — stateless flow, can't share verifier across requests).
- `GET /auth/callback` → exchanges code, upserts user in Supabase, AES-GCM encrypts Drive tokens, redirects with JWT.
- `middleware/auth.py`: Bearer JWT → `request.state.user_id` on every request (public: `/health`, `/auth/*`).
- Frontend: `AuthContext` injects `Authorization: Bearer <jwt>` on all requests. 401 auto-reloads.

**Scope relaxation**: `OAUTHLIB_RELAX_TOKEN_SCOPE=1` — Google reorders/drops scopes under granular consent; without this the token exchange errors. Missing `drive.file` → falls back to local filesystem storage.

---

### Google Drive Storage

User data lives on the user's own Google Drive (`PAWN/`). PAWN holds no user content.

```
PAWN/
  conversations/{conv_id}/
    meta.json
    messages.jsonl
    summary.md
  uploads/{doc_id}.txt
```

`core/drive_factory.py` `get_drive_for_user(user_id)` → decrypts tokens from Supabase → builds `DriveStorage` → or `None` on any failure. Every route that calls it falls back to local filesystem on `None`. Tests always hit local fallback (no real Supabase/Drive in CI).

**Performance hardening:**
- `googleapiclient` and `supabase-py` are synchronous. Every Drive/Supabase call is moved off the async event loop via `run_in_threadpool` / `asyncio.to_thread`.
- `DriveStorage` caches file IDs — reads go by ID via `files.get_media` (strongly consistent) instead of eventually-consistent name queries.
- Per-user `DriveStorage` instances cached with TTL (10 min live / 30 s not-linked). Re-entrant lock guards the shared instance (httplib2 is not thread-safe across threadpool workers).
- 20s socket timeout on all Drive HTTP calls.

---

### Optimistic UI + Client-Side Store

Conversation IDs are generated client-side (`crypto.randomUUID()`). Backend `POST /conversations` is idempotent on caller-supplied ID. `/chat` lazy-creates the conversation on first message.

**Store layer (`frontend/src/store/`):**
- `conversationCache.ts` — localStorage cache of list + messages per user. LRU(30), ~4 MB eviction, corruption-safe, `mergeServerMeta` reconciliation.
- `syncQueue.ts` — persisted create/rename/delete queue, exponential backoff, DELETE-404-as-success, drains on `online`, survives reload. Sidebar shows pending-sync dots + offline banner.
- `useConversationStore.ts` — single owner of list/messages/active selection. All mutations optimistic (local first).

**Draft new chat**: clicking New Chat opens a frontend-only draft (no sidebar row, no backend call). Materialized on first send via `promoteDraft`. At most one draft.

**Per-conversation streaming**: `streamsRef` is a `Map<convId, {controller, ...}>`. Streaming in conversation A while B is streaming works — independent `AbortController`s. Rate-limit countdown is per-conversation.

---

### Kaggle GPU Image Generation

Two models running on the user's own Kaggle account:

| Model | GPU | Warm load | Inference (warm) |
|---|---|---|---|
| SDXL (`stabilityai/stable-diffusion-xl-base-1.0`) | Single T4 | ~1–2 min | seconds |
| FLUX.1-schnell (`black-forest-labs/FLUX.1-schnell`) | Dual T4, bf16, `device_map="balanced"`, VAE tiling | ~10 min | seconds |

**Warm session architecture:**
Instead of spinning a new Kaggle container per image, a persistent kernel loads the model once and polls Supabase for jobs.

- `image_sessions` table: one row per live session (status, heartbeat, expiry).
- `image_jobs` table: one row per generation (status: queued/running/done/error, prompt, params, result PNG as base64).
- Kaggle notebook: loads model once → PATCHes `installing → loading_model → ready` at phase boundaries → serve loop (heartbeat, pick next queued job, run inference, PATCH done + PNG, honor stop/timer).
- Only the **public Supabase anon key** is injected into the notebook payload (base64-encoded). Service key never leaves the backend.

**Durable cold jobs:**
`POST /generate` is non-blocking — creates a `queued` row, fires a GC-safe background worker (strong `asyncio.Task` reference via `_spawn_bg` — `create_task` alone keeps only a weak ref), returns `{job_id}`. Frontend polls `GET /generate/job/{id}` at 3s intervals. Results survive refresh and tab switches.

**Double-submit prevention (server-derived):**
`create_cold_job` deduplicates by `(user_id, model_id)` — returns the existing job ID if one is queued/running. Frontend derives button disabled state from a `listJobs` poll — holds across refresh and across browser tabs.

**img2img:**
`ImageJobParams` carries `init_image_b64` (direct upload) or `init_job_id` (reference a prior generation, user-scoped). `strength` (0–1) controls influence. SDXL warm: `AutoPipelineForImage2Image.from_pipe(pipe)`. FLUX warm: `FluxImg2ImgPipeline(**pipe.components)`. Both reuse already-loaded weights.

**Advanced params:** inference steps, guidance scale, negative prompt, aspect ratio, style preset (applied as a prompt suffix on the backend).

**Self-healing reaper (`reap_stale_jobs`, called every `listJobs` poll):**
Fails cold jobs stuck past 20 min wall-clock. Fails session jobs whose session is no longer alive (ended/stopped/expired/heartbeat stale by 90s). Prevents stuck-button state after external kernel kills.

---

### Backend Patterns

- All singletons built in `app_initializer.initialize_managers()`, injected via router factories. No module-level globals in routes.
- Domain exceptions (`ProviderError`, `NoEndpointError`) in `exceptions.py`, registered as HTTP handlers in `main.py`. Routes never `try/except` expected failures.
- `constants.py` — single source of truth for all file paths.
- `events.py` — only place SSE frames are constructed.

**Middleware stack:**
1. GZip
2. Timeout (45s, SSE exempt)
3. Security headers (X-Frame-Options, CSP, X-Content-Type-Options, Referrer-Policy)
4. CORS (restricted to `localhost:5174`)
5. Auth (JWT Bearer → `request.state.user_id`)

**Secrets pattern:** Docker secret files at `/run/secrets/<name>`. `config.py` `read_secret()` checks that path first, then env var fallback for local runs. API keys never touch the codebase or environment dumps.

---

## Running the Stack

```bash
# Prerequisites: Docker Desktop, real values in secrets/
docker compose up
```

Backend: `http://localhost:8001` · Frontend: `http://localhost:5174`

**Required secrets before first run:**

| File | What |
|---|---|
| `secrets/supabase_url` | Supabase project URL |
| `secrets/supabase_service_key` | Supabase service role key (`sb_secret_...`) |
| `secrets/google_client_id` | Google OAuth2 Web client ID |
| `secrets/google_client_secret` | Google OAuth2 Web client secret |
| `secrets/encryption_secret` | Random 32-byte hex (pre-generated at setup) |
| `secrets/jwt_secret` | Random 32-byte hex (pre-generated at setup) |
| `secrets/supabase_anon_key` | Supabase public anon key (for Kaggle notebook) |

**One-time Supabase setup:** run `supabase/schema.sql` in your Supabase project (creates `memory_chunks`, `image_sessions`, `image_jobs` tables + pgvector RPCs).

---

## Testing

```bash
# Backend
docker compose exec backend pytest

# Frontend (build gate — no unit tests)
cd frontend && npm run build
```

139 backend tests at time of writing. One test file per route module. Provider calls always mocked. `conftest.py` `bypass_auth` fixture injects `user_id="test-user-id"`. `stub_byok_key` autouse fixture patches `key_store.get_key` so resolver doesn't raise during tests.

---

## Project Structure

```
backend/
  app/
    core/          # normalize.py, llm_core.py, resolver.py, crypto.py, key_store.py
    db/            # supabase_client.py
    memory/        # embed.py, index.py, retrieve.py, summarize.py
    middleware/    # auth.py, security.py, timeout.py
    routes/        # chat.py, conversations.py, upload.py, keys.py, auth.py, generate.py
    storage/       # conversations.py, documents.py, drive.py, conversations_drive.py, documents_drive.py
    events.py      # SSE builder functions
    constants.py   # all file paths
    config.py      # read_secret()
  tests/
data/
  registry/        # models.json, endpoints.json
kaggle_templates/  # image_flux_session/, image_sdxl_session/, image_gen/
supabase/          # schema.sql
frontend/
  src/
    api/           # client.ts
    components/    # ImageLabPage, GenerationsPanel, SessionBar, ModelSwitcher, ApiKeysSection, ...
    contexts/      # AuthContext.tsx, AppContext.tsx
    pages/         # Layout.tsx, ChatPage.tsx, SettingsPageWrapper.tsx, ImageLabPageWrapper.tsx
    store/         # useConversationStore.ts, conversationCache.ts, syncQueue.ts
    types.ts
workspace/
  plan/            # phase plans
  implemented_phases/
  status/          # build_tracker.md, dev_log.md
  decisions/       # architecture decision records
```

---

## Key Engineering Decisions

**Google Drive as user storage (not a shared database):** Each user's data is isolated in their own Drive. PAWN acts as a proxy — it never holds user content at rest. The tradeoff is Drive latency and eventual consistency, both addressed by the file-ID cache and threadpool offloading.

**BYOK-only in production:** Shared Docker-secret provider keys are retained for dev/test but unused in production once BYOK is configured. Every LLM and embedding call resolves through the user's own key. A user without a key gets a clear actionable error, not a silent failure.

**Kaggle as compute, Supabase as rendezvous:** Kaggle provides free GPU quota (T4, dual-T4). The warm-session design uses Supabase as a message queue — the notebook polls for jobs, the backend polls for results. No persistent connection, no webhook surface, no custom infrastructure.

**Optimistic UI with a persisted sync queue:** Drive latency (200–800ms per call) makes server-round-trip UI unusable. Client-owned UUIDs + localStorage cache make every conversation action instant. The sync queue handles retries, ordering, and offline survival so Drive stays consistent without the user ever waiting on it.
