# PAWN — Personal AI Workspace

Multi-model, multi-user BYOK AI chat application. One interface, multiple LLM providers, transparent rate-limit failover, persistent scoped memory, a LangGraph tool-using agent, an optional operator-funded shared key pool, and on-demand GPU image generation via Kaggle — all with user content stored on the user's own Google Drive.

Built solo. No starter templates, no AI backend services — auth, streaming, GPU orchestration, and storage implemented directly.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 19, Vite 8, TypeScript, Tailwind v4 |
| Routing | react-router-dom |
| Markdown | react-markdown |
| Backend | FastAPI (Python 3.12), Pydantic v2, fully async |
| Streaming | Server-Sent Events (SSE) via `StreamingResponse` |
| Auth | Google OAuth2 (confidential client) + email/password (Argon2id), PyJWT (HS256, 7-day sessions) |
| Encryption | AES-256-GCM via Python `cryptography` (BYOK keys + Drive tokens at rest) |
| Agent | LangGraph `StateGraph` (classify, plan, execute, verify; native tool calling; `AsyncSqliteSaver` checkpointer) |
| Memory retrieval | pgvector + PostgreSQL FTS, RRF fusion |
| Text embeddings | Google `gemini-embedding-2` (768-dim) |
| Database | PostgreSQL + pgvector (`psycopg3`), a local container on the same VM: accounts, encrypted keys, embeddings, usage, image jobs |
| API layer | Self-hosted PostgREST (rendezvous for the Kaggle image-gen loop) |
| File storage | Google Drive API (per-user, `drive.file` scope) |
| Image generation | Kaggle Kernels API — SDXL + FLUX.1-schnell on T4 / dual-T4 GPU |
| Infrastructure | Docker Compose, secrets-as-files, host Nginx + certbot on a single GCP `e2-micro` VM |
| Testing | pytest (800+ backend tests), Vitest, `tsc` + `vite build` as the frontend gate |

---

## Architecture

### Multi-Provider LLM Routing

All LLM calls go through `backend/app/core/normalize.py` → `llm_core.py`. Routes and agents never call providers directly.

11 providers (Google, Groq, Cerebras, HuggingFace, GitHub Models, OpenRouter, Mistral, NVIDIA, SambaNova, Kluster, Zhipu) across 47 endpoints use the OpenAI-compatible chat completions wire format. `llm_core.py` speaks one protocol; `normalize.py` swaps the base URL, auth header, and model name per provider. No provider SDKs — no vendor lock-in.

The model registry lives in `backend/data/registry/` (`models.json`, `endpoints.json`, `providers.json`): JSON files, not code. Adding a provider means editing JSON.

**Rate-limit resilience (`backend/app/core/resolver.py`, `rate_limiter.py`):**
- `EndpointRateLimiter` tracks rolling RPM and TPM per endpoint.
- At 90% of a limit the endpoint is soft-blocked before a real 429 arrives.
- On a live 429 the endpoint enters a cooldown. After N consecutive failures it is marked dead-host.
- Cross-model fallback: if the selected model is rate-limited before the first token, `chat_stream` iterates `fallback_models` (same capability level, user-keyed) and switches transparently — emitting a `provider_switch` SSE event rendered as an inline notice in the chat.

**BYOK (Bring Your Own Key):**
- Users configure keys on the Providers page. Keys are AES-256-GCM encrypted and stored in Postgres, scoped by `user_id`. Key values are never returned by any API endpoint.
- `resolver.pick(model_id, user_id)` prefers the user's own key, then falls back to the operator pool key (if the endpoint allows it and fair-share quota permits). No usable key → clear error: *"Add your provider key in Settings."*
- Keys are decrypted once per request window via a short-TTL cache (`core/key_store.py`).
- **Operator pool keys**: an admin role (`core/admin.py`, `routes/admin.py`) can configure shared, DB-backed provider keys (`core/pool_key_store.py`) that users draw from a shared quota (`core/quota_share.py`) when they haven't configured their own — surfaced on a `/providers` dashboard (`routes/dashboard.py`).

---

### Streaming (SSE)

Backend: `StreamingResponse` with `text/event-stream`. Every response is a stream of **typed JSON events** — never raw strings.

Typed events defined in `backend/app/events.py` (core ones shown):

| Type | Carries |
|---|---|
| `token` | streaming text delta |
| `done` | stream end + provider name |
| `error` | sanitized error message + optional code |
| `provider_switch` | failover notice |
| `step` | LangGraph agent step |
| `tool_result` | a tool call's observation |
| `citation` | source cited by a search/fetch tool |
| `memory_hit` | retrieved memory chunk |
| `model_call` | secondary model invocation |

`X-Accel-Buffering: no` and `Cache-Control: no-cache` headers prevent proxy buffering. The 45s timeout middleware exempts SSE paths.

Frontend (`frontend/src/api/client.ts`): `streamChat()` opens a `fetch` + `ReadableStream` + `TextDecoder` pipeline. Dispatches on `event.type` into a `StreamChatCallbacks` object. Components receive typed callbacks — they never parse raw SSE.

---

### LangGraph Agent

A `StateGraph` replaces a single LLM call: `classify -> direct_answer` (simple turns) or `classify -> plan -> execute -> verify` (heavier turns).

- **`classify`**: a heuristic router (with an LLM fallback) sets difficulty, task type and whether tools are needed; the composer's Fast / Pro / Image hint can override it.
- **`execute`**: a streaming tool loop using native OpenAI-style tool calling (iteration and token budgets). Tools: calculator, datetime, `fetch_url` (SSRF-guarded), `web_search` (Tavily/Brave via the user's own key), `search_memory`, `doc_search`, `generate_image`. Three preset subagents (researcher, summarizer, coder) can be delegated to, one level deep.
- **`verify`**: for research-style heavy turns, a research-tier model checks the buffered draft against the request and can send the loop back for up to two revisions.
- **Model choice**: the user's explicit pick wins for the final answer; helper steps are chosen by capability level (fast / balanced / research) from the registry.
- **Checkpointer**: `AsyncSqliteSaver` persists state by `{user_id}:{conv_id}`.
- Events from nodes flow through `astream_events` and are emitted as `step` / `tool_result` / `citation` / `memory_hit` / `model_call` SSE events, shown in a collapsible inline trace per message.

---

### Memory and RAG

Memory is scoped: each standalone chat has its own memory, and each project has a shared memory for the chats inside it. Folder placement in Drive decides the scope.

1. Messages and uploaded documents are chunked and written to the chat's `rag_chunks.jsonl` on Google Drive first, then embedded (`gemini-embedding-2`, 768-dim) and indexed in Postgres `memory_chunks` (pgvector). Postgres is a rebuildable index; "Rebuild memory" re-derives it from Drive.
2. Every 20 messages a fast-tier model writes a bullet summary to `summary.md`, which is re-indexed.
3. The `search_memory` / `doc_search` tools retrieve via vector search (`match_scoped_chunks`) and full-text search (`search_scoped_chunks`), fused with Reciprocal Rank Fusion.
4. Hits are surfaced in the UI as `memory_hit` events with provenance.

All rows are scoped by `user_id` and scope; a chat only sees its own chunks and a project only its project's.

**Graceful degradation**: Postgres down -> retrieval returns `[]`. Embedding fails (no Google key from the user or pool) -> full-text only. The agent still answers.

---

### Auth + Multi-User

**OAuth2 flow:**
- `GET /auth/login` → Google OAuth2 (confidential client, PKCE disabled — stateless flow, can't share verifier across requests).
- `GET /auth/callback` → exchanges code, upserts user in Postgres, AES-GCM encrypts Drive tokens, redirects with JWT.
- `middleware/auth.py`: Bearer JWT → `request.state.user_id` on every request (public: `/health`, `/auth/*`).
- Frontend: `AuthContext` injects `Authorization: Bearer <jwt>` on all requests. 401 auto-reloads.

**Scope relaxation**: `OAUTHLIB_RELAX_TOKEN_SCOPE=1` — Google reorders/drops scopes under granular consent; without this the token exchange errors. Drive is mandatory for anything that stores data: without a working `drive.file` grant, storage routes return HTTP 412 `not_configured` and the UI points the user to Providers.

**Email/password auth:**
- `routes/account.py` implements split sign-in/sign-up plus change-password, hashed with Argon2id (`core/password_utils.py`) — no OAuth dependency for users who prefer a local account.
- `core/login_rate_limiter.py` throttles repeated failed logins per account/IP.

---

### Google Drive Storage

User content lives on the user's own Google Drive (`PAWN/` in prod, `PAWN-dev/` locally). PAWN's database holds no conversations.

```
PAWN/
  conversations/
    chats/{conv_id}/          meta.json, messages.jsonl, summary.md, rag_chunks.jsonl
    projects/{project_id}/    project.json, {conv_id}/ (same shape as a chat)
  uploads/{doc_id}.txt
```

`core/drive_factory.py` `get_drive_for_user(user_id)` → decrypts tokens from Postgres → builds `DriveStorage` . `require_drive_for_user` raises a 412 when Drive is not linked (stateless chat without a conversation or document still works). Tests use an in-memory `FakeDriveStorage`.

**Performance hardening:**
- `googleapiclient` is synchronous. Every Drive call is moved off the async event loop via `run_in_threadpool` / `asyncio.to_thread`.
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
Instead of spinning a new Kaggle container per image, a persistent kernel loads the model once and polls the self-hosted PostgREST API for jobs.

- `image_sessions` table: one row per live session (status, heartbeat, expiry).
- `image_jobs` table: one row per generation (status: queued/running/done/error, prompt, params, result PNG as base64).
- Kaggle notebook: loads model once → PATCHes `installing → loading_model → ready` at phase boundaries → serve loop (heartbeat, pick next queued job, run inference, PATCH done + PNG, honor stop/timer).
- Only the **public PostgREST anon role credential** is injected into the notebook payload (base64-encoded). The main Postgres password never leaves the backend.

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
4. CORS (env-driven allow-list; `*` is rejected at startup)
5. Auth (JWT Bearer → `request.state.user_id`)

**Secrets pattern:** Docker secret files at `/run/secrets/<name>`. `config.py` `read_secret()` checks that path first, then env var fallback for local runs. API keys never touch the codebase or environment dumps.

---

## Running the Stack

```bash
# Prerequisites: Docker Desktop, real values in secrets/
docker compose up
```

Backend: `http://localhost:8001` · Frontend: `http://localhost:5174`

**Production** runs on a single GCP `e2-micro` VM (backend + local Postgres + PostgREST in Docker, static frontend and TLS via host Nginx). See `deployment.md`.

**Required secrets before first run:**

| File | What |
|---|---|
| `secrets/postgres_dsn` | App DB connection string (backend → Postgres) |
| `secrets/postgres_password` | Postgres superuser/app password |
| `secrets/postgrest_db_uri` | DB URI PostgREST connects with (scoped `pawn_anon` role) |
| `secrets/postgrest_anon_password` | Password for the `pawn_anon` role exposed to the Kaggle notebook |
| `secrets/shared_db_dsn` | DSN for the shared/pool-key tables |
| `secrets/google_client_id` | Google OAuth2 Web client ID |
| `secrets/google_client_secret` | Google OAuth2 Web client secret |
| `secrets/encryption_secret` | Random 32-byte hex (pre-generated at setup) |
| `secrets/jwt_secret` | Random 32-byte hex (pre-generated at setup) |
| `secrets/pool_<provider>_api_key` | Optional shared provider keys for the operator pool-key system |

**Database setup:** on an empty Postgres volume, `postgres/schema.sql` runs automatically (compose mounts it into `docker-entrypoint-initdb.d`) and creates `users`, `user_api_keys`, `pool_api_keys`, `user_drive_tokens`, `memory_chunks`, `image_sessions`, `image_jobs`, `endpoint_usage`, etc., with `pgvector`/`pgcrypto` and the `match_scoped_chunks`/`search_scoped_chunks` functions. Later schema changes are applied by hand from `postgres/migrations/`. `postgres/init_pawn_anon.sh` sets up the restricted `pawn_anon` role PostgREST uses.

---

## Testing

```bash
# Backend
docker compose exec backend pytest

# Frontend (type-check + build gate; a few Vitest unit tests)
cd frontend && npm run build
```

800+ backend tests. One test file per route module. Provider calls always mocked. `conftest.py` `bypass_auth` fixture injects `user_id="test-user-id"`. `stub_byok_key` autouse fixture patches `key_store.get_key` so resolver doesn't raise during tests.

---

## Project Structure

```
backend/
  app/
    agent/         # graph.py, subagents.py, tools/
    core/          # normalize.py, llm_core.py, router.py, rate_limiter.py, usage_store.py, quota_share.py,
                   # key_store.py, pool_key_store.py, crypto.py, kaggle.py, image_session.py, image_models.py,
                   # drive_factory.py, jwt_utils.py, password_utils.py, vision_enhance.py, ...
    resolver/      # resolver.py (endpoint picking, capability ranking, fallbacks)
    memory/        # chunker, embed, index, indexer, retrieve, summarize
    storage/       # drive.py, conversations_drive.py, projects_drive.py, documents_drive.py
    db/            # postgres_client.py
    middleware/    # auth.py, security.py, timeout.py
    registry/      # loader, schemas, providers
    routes/        # chat, conversations, upload, keys, auth, account, admin, dashboard, generate, memory, projects, registry, crypto
    kaggle_templates/  # session + cold notebooks (SDXL, FLUX)
    events.py      # SSE builders
    constants.py   # paths and tunables
    config.py      # read_secret()
  data/registry/   # models.json, endpoints.json, providers.json, image_presets.json
  tests/
postgres/          # schema.sql, migrations/, init_pawn_anon.sh
scripts/           # promote-to-main.sh, backup-db.sh
frontend/
  src/
    api/           # client.ts (all API/SSE calls)
    components/    # chat, sidebar, Image Lab, Providers, settings, dialogs
    contexts/      # AuthContext.tsx, AppContext.tsx
    pages/         # Layout, ChatPage, ProjectPage, ProvidersPage, SettingsPageWrapper, ImageLabPageWrapper, ...
    store/         # useConversationStore.ts, conversationCache.ts, syncQueue.ts
    types.ts
workspace/         # dev-only docs (stripped from main); OVERVIEW.md is the plain-language current picture
```

---

## Key Engineering Decisions

**Google Drive as user storage (not a shared database):** Each user's data is isolated in their own Drive. PAWN acts as a proxy — it never holds user content at rest. The tradeoff is Drive latency and eventual consistency, both addressed by the file-ID cache and threadpool offloading.

**BYOK-first with an optional operator pool:** every LLM and embedding call prefers the user's own key. If the operator (admin) has configured a shared pool key for that provider, a keyless user falls back to it under a fair-share quota. A user with neither gets a clear actionable error, not a silent failure.

**Kaggle as compute, self-hosted PostgREST as rendezvous:** Kaggle provides free GPU quota (T4, dual-T4). The warm-session design uses PostgREST as a message queue — the notebook polls for jobs, the backend polls for results. No persistent connection, no webhook surface; in production Nginx exposes PostgREST at `/pgrst/`, and access is limited by a restricted database role plus per-session-token row-level security.

**Optimistic UI with a persisted sync queue:** Drive latency (200–800ms per call) makes server-round-trip UI unusable. Client-owned UUIDs + localStorage cache make every conversation action instant. The sync queue handles retries, ordering, and offline survival so Drive stays consistent without the user ever waiting on it.

---

## Acknowledgements

PAWN's multi-provider routing and free-tier failover design was informed by
[OmniRoute](https://github.com/diegosouzapw/OmniRoute) (MIT), an open-source AI
gateway that aggregates free-tier capacity across many providers behind a single
OpenAI-compatible endpoint. PAWN shares no code with it — the influence is on
approach: a data-driven provider registry, priority-ordered failover, and honest
per-endpoint quota accounting.
