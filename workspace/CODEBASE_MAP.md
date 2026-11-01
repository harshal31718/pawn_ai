# PAWN — Project Outline

> **Audience: AI agents.** Code-derived map of the repo (what each module does, data flow, APIs, storage, config). Generated 2026-10-04 from a read-through of `dev`, corrected 2026-11-01 for the prod database change (Supabase dropped 2026-10-30; prod Postgres is a local container again). Section 6 doubles as the API reference.
> Where this file and the code disagree, the code wins; fix this file. Section 13 lists known sharp edges. Human summary: `workspace/OVERVIEW.md`. Why things are the way they are: `workspace/decisions/change_log_2026.md`.

---

## Table of Contents

1. Project Overview
2. Tech Stack
3. Folder and File Structure
4. Components and Modules
5. Data Flow and Architecture
6. APIs and Interfaces
7. Core Logic and Algorithms
8. Data Storage
9. Configuration and Environment
10. External Integrations
11. Entry Points and Execution Flow
12. Testing
13. Known Issues, TODOs, Incomplete Areas, Doc/Code Drift
14. Glossary

---

## 1. Project Overview

**What it is.** PAWN ("Personal AI Workspace") is a multi-user, multi-provider, **bring-your-own-key (BYOK)** AI chat application. One chat interface sits in front of 11 LLM providers (Google Gemini, Groq, Cerebras, Hugging Face, GitHub Models, OpenRouter, Mistral, NVIDIA NIM, SambaNova, Kluster, Zhipu/GLM). It adds:

- **Transparent rate-limit failover** — per-endpoint quota tracking, soft-blocking at 90% of a published limit, cooldowns on 429, then cross-endpoint and cross-model fallback while a stream is being produced.
- **A LangGraph agent** — classify → (direct answer | plan → execute tool-loop → optional verify), with native OpenAI-style tool calling, three preset subagents, and web search / URL fetch / calculator / datetime / memory / document / image-generation tools.
- **Scoped persistent memory (RAG)** — per-chat or per-project memory in Postgres + pgvector, hybrid vector + full-text retrieval fused with Reciprocal Rank Fusion.
- **User data on the user's own Google Drive** — conversations, summaries, RAG chunk source files, uploads and projects live under `PAWN/` (or `PAWN-dev/`) in each user's Drive (`drive.file` scope). The backend keeps only accounts, encrypted keys/tokens, embeddings and image-job state.
- **GPU image generation on the user's own Kaggle account** — SDXL and FLUX.1-schnell, via either one-shot "cold" kernel runs or persistent "warm sessions" that rendezvous with the backend through a self-hosted PostgREST instance.
- **An operator "pool"** — an admin (one hardcoded email) can register shared provider keys that keyless users fall back to, with a fair-share quota algorithm ported from OmniRoute.

**Target users.** A solo operator plus a small number of friends/testers (the docs describe "early testing", a published-but-unverified Google OAuth consent screen, and a single small GCP VM). Casual daily AI users frustrated by per-provider rate limits and lost context.

**Architecture style.** Client–server, split into a Vite/React SPA and a single FastAPI (ASGI) process, with Postgres (+pgvector) and PostgREST as side services. No microservices, no job queue: background work is `asyncio` tasks / FastAPI `BackgroundTasks` / thread-pool calls inside the one backend process. Communication between SPA and API is **REST + Server-Sent Events only** (an explicit project rule: no shared code between the stacks).

**Operating model.** `dev` is the working branch; `main` is deploy-only and has `.claude/`, `workspace/`, `CLAUDE.md`, `AGENTS.md` stripped by `scripts/promote-to-main.sh`. Production runs on a GCP `e2-micro` VM (`pawnai.duckdns.org`) with a local, memory-capped Postgres container (Supabase was used 2026-08-30 to 2026-10-30, then dropped); local dev runs everything in Docker Compose.

**Non-negotiable project rules** (from `CLAUDE.md`, `.claude/CLAUDE.md`, `.claude/rules/*`):

1. All LLM calls go through `backend/app/core/normalize.py` (never call `llm_core.py` from routes).
2. Secrets come from `/run/secrets/*` via `app/config.read_secret()`; never inlined, never `.env` for secrets.
3. Tests must pass before a step is marked done.
4. Never commit real files in `secrets/` (only `.gitkeep` and `*.example`).
5. Frontend and backend talk only via REST + SSE.
6. Update `workspace/current_state.md` and `workspace/status/dev_log.md` after every step.
7. SSE frames are built only by `app/events.py` builders.
8. `app/constants.py` is the single source of truth for file paths.
9. Singletons are built once in `app_initializer.initialize_managers()`; domain exceptions are registered as HTTP handlers (no try/except for expected failures in routes); CORS never `*`; `SecurityHeadersMiddleware` never removed.

---

## 2. Tech Stack

### Backend (Python 3.12, `python:3.12-slim` image)

`backend/requirements.txt` (almost entirely **unpinned**; only the LangGraph pair has bounds):

| Package | Pin | Used for |
|---|---|---|
| `fastapi`, `uvicorn[standard]`, `pydantic` (v2) | none | API server, request/response models |
| `httpx`, `httpx2` | none | Async HTTP to LLM providers, search APIs, Gemini embeddings; sync client for Kaggle. (`httpx2` is listed but I found no import of it in the files I read.) |
| `langgraph` | `>=1.2.0,<2.0.0` | Agent `StateGraph`. Upper bound added 2026-07-23 after 0.6.x broke `adispatch_custom_event` |
| `langchain-core` | none | `adispatch_custom_event`, callbacks used by `astream_events` |
| `langgraph-checkpoint-sqlite` | `>=3.0.1,<4.0.0` | `AsyncSqliteSaver` checkpointer (`checkpoints.db`) |
| `psycopg[binary]` | `>=3.1` | Sync Postgres access (psycopg3, dict rows) |
| `pgvector` | `>=0.3.0` | `register_vector` so lists bind to `vector(768)` |
| `cryptography` | none | AES-256-GCM for BYOK keys, pool keys, Drive tokens |
| `argon2-cffi` | none | Argon2id password hashing |
| `PyJWT` | none | HS256 session tokens (7 days) |
| `google-auth-oauthlib`, `google-api-python-client`, `google-auth-httplib2` | none | Google OAuth2 + Drive v3 |
| `trafilatura` | none | Readable-text extraction for `fetch_url` / `web_search` body enrichment |
| `pdfplumber`, `python-multipart` | none | PDF text extraction and multipart uploads |
| `numpy` | none | Listed; no direct use seen in the files read |
| `pytest`, `pytest-asyncio`, `pytest-xdist` | none | Test stack (installed in the runtime image too) |

### Frontend (`frontend/package.json`, Node 20 image)

| Package | Version | Role |
|---|---|---|
| `react`, `react-dom` | `^19.0.0` | UI |
| `react-router-dom` | `^7.18.1` | Routing |
| `react-markdown` | `^10.1.0` + `remark-gfm ^4.0.1` | Assistant message rendering |
| `vite` | `^8.0.16` | Build/dev server (`@vitejs/plugin-react ^6.0.2`) |
| `tailwindcss` + `@tailwindcss/vite` | `^4.0.0` | Styling (v4, CSS-first, theme tokens like `bg-theme-*`) |
| `typescript` | `~5.6.2` | Types (`tsc -b && vite build`) |
| `vitest` | `^4.1.9` | Unit tests (script `npm test` → `vitest run`) |

Fonts are self-hosted woff2 (Fraunces, IBM Plex Mono, Instrument Sans) in `frontend/public/fonts/`.

### Infrastructure

| Component | Version / image |
|---|---|
| Postgres + pgvector | `pgvector/pgvector:pg16` in both dev and prod compose (prod: `mem_limit: 200m`, `shared_buffers=32MB`) |
| PostgREST | `postgrest/postgrest:v12.2.3` |
| SSH tunnel helper containers | `alpine:3.20` + `openssh-client` (dev profile `tunnel`) |
| Reverse proxy / TLS | host Nginx + certbot (config lives only in `deployment.md`, not in the repo as a file) |
| Prod host | GCP `e2-micro` (1 shared vCPU / 1 GB RAM), Ubuntu 24.04 x86_64, DuckDNS domain |
| Compute for images | Kaggle Kernels (T4 / T4×2), `diffusers`, `transformers`, `accelerate`, `torch` installed inside notebooks |
| LLM wire format | OpenAI-compatible `POST {base_url}/chat/completions` for **every** provider (Google via its OAI-compat endpoint); no provider SDKs |

---

## 3. Folder and File Structure

Tracked files: 349 (`git ls-files`). About 61k lines in total, of which `package-lock.json` is ~6.9k.

```text
PAWN/
├── CLAUDE.md                     Root pointer for Claude Code (points into .claude/ and workspace/)
├── AGENTS.md                     Root pointer for non-Claude agents
├── README.md                     Public-facing project description (partly stale, see §13)
├── deployment.md                 GCP e2-micro deployment runbook: Nginx config, secrets, local Postgres, backups, rollback
├── docker-compose.yml            Local dev stack: backend, postgres, postgrest, frontend, + tunnel profile services
├── docker-compose.prod.yml       Prod/staging stack: backend + postgres + postgrest, env-file driven, memory-capped for the 1 GB e2-micro
├── docker-compose.override.yml.example   Local-only override that points POSTGREST_PUBLIC_URL at the dev tunnel
├── .env.prod.example / .env.staging.example   Non-secret per-env values (ports, domains, PAWN_ENV, URLs)
├── .gitignore / .gitattributes / .dockerignore
├── scripts/
│   └── promote-to-main.sh        dev→main merge that strips .claude/, workspace/, CLAUDE.md, AGENTS.md from main
├── secrets/                      Docker-secret source files (gitignored); only .gitkeep + *.example are tracked
│   ├── encryption_secret.example, jwt_secret.example, google_client_id.example, google_client_secret.example
│   ├── postgres_dsn.example, postgres_password.example, postgrest_db_uri.example, postgrest_anon_password.example
│   ├── shared_db_dsn.example
│   └── pool_<provider>_api_key.example   (11 providers: cerebras, github, google, groq, huggingface, kluster, mistral, nvidia, openrouter, sambanova, zhipu)
├── postgres/
│   ├── schema.sql                Full schema + SQL functions + pawn_anon role + RLS policies
│   ├── init_pawn_anon.sh         Sets pawn_anon's password from a Docker secret (runs after schema.sql in initdb.d)
│   └── migrations/               8 hand-applied SQL migrations (2026-07_*), see §8
├── backend/
│   ├── Dockerfile, requirements.txt
│   ├── app/
│   │   ├── main.py               FastAPI app, middleware stack, exception handlers, router registration, /health
│   │   ├── app_initializer.py    initialize_managers(): registry, rate limiter, resolver, SQLite checkpointer, compiled graph
│   │   ├── config.py             read_secret(), pool-key reader, env-var driven URLs, PAWN_ENV
│   │   ├── constants.py          All paths, timeouts, role→capability tables, thresholds (single source of truth)
│   │   ├── events.py             SSE event builders (token, done, error, step, tool_result, citation, ...)
│   │   ├── exceptions.py         ProviderError, NoEndpointError, NotConfiguredError(412), KaggleError(502), UnknownModelError(400) + handlers
│   │   ├── agent/                LangGraph agent
│   │   │   ├── graph.py          AgentState + classify/direct_answer/plan/execute/verify nodes + build_agent_graph()
│   │   │   ├── subagents.py      researcher / summarizer / coder presets and run_subagent()
│   │   │   ├── oai_tools.py      ToolSpec → OAI tool schema, citation extraction from observations
│   │   │   └── tools/            base.py, registry.py, execute.py (run_tool), calculator, get_datetime, fetch_url, web_search, search_memory, doc_search, generate_image
│   │   ├── core/                 Provider layer, quota, keys, images, Kaggle
│   │   │   ├── normalize.py      THE single entry for LLM calls: chat_stream, chat_complete, chat_stream_with_tools, chat_complete_single_model
│   │   │   ├── llm_core.py       Raw httpx streaming/non-streaming calls to {base_url}/chat/completions
│   │   │   ├── router.py         Difficulty/task-type classifier (heuristic + LLM fallback) and resolve_final_model
│   │   │   ├── rate_limiter.py   EndpointRateLimiter (rpm/tpm in-memory, rpd/tpd persisted, cooldowns)
│   │   │   ├── usage_store.py    Postgres persistence for day/month usage windows (with circuit breaker)
│   │   │   ├── quota_share.py    Fair-share enforcement for pool-sourced calls
│   │   │   ├── key_store.py      Per-user encrypted BYOK keys + Kaggle credentials (TTL cache)
│   │   │   ├── pool_key_store.py Operator pool keys in Postgres (admin-editable, TTL cache)
│   │   │   ├── crypto.py         AES-256-GCM encrypt/decrypt
│   │   │   ├── jwt_utils.py, password_utils.py, login_rate_limiter.py, admin.py
│   │   │   ├── drive_factory.py  Cached per-user DriveStorage + require_drive_for_user / call_drive
│   │   │   ├── generate.py       Kaggle modality dispatch (connect, cold image run, cube POC)
│   │   │   ├── image_models.py   ImageModel registry (sdxl, flux), PromptSchema, resolution buckets, negative-prompt merge
│   │   │   ├── image_presets.py  Loader for backend/data/registry/image_presets.json
│   │   │   ├── image_session.py  Warm sessions + durable job layer (largest core module, 760 lines)
│   │   │   ├── kaggle.py         Kaggle REST client (push, status, output, 409 handling)
│   │   │   ├── vision_enhance.py Vision-grounded prompt enhancer (Groq→Gemini chain)
│   │   │   └── title.py          Fallback conversation title
│   │   ├── db/postgres_client.py psycopg3 helpers: fetchone/fetchall/execute/transaction, optional dsn override
│   │   ├── memory/               chunker.py, embed.py, index.py, indexer.py, retrieve.py, summarize.py, locks.py
│   │   ├── middleware/           auth.py (JWT), security.py (headers+CSP), timeout.py (45 s, SSE exempt)
│   │   ├── registry/             loader.py, schemas.py, providers.py, seed.py
│   │   ├── resolver/resolver.py  Resolver: endpoint picking, key resolution, capability ranking, fallback_models
│   │   ├── routes/               account, admin, auth, chat, conversations, crypto, dashboard, generate, keys, memory, projects, registry, upload
│   │   ├── storage/              drive.py (Drive v3 wrapper), conversations_drive.py, projects_drive.py, documents_drive.py
│   │   └── kaggle_templates/     5 .ipynb notebooks: cube_poc, image_sdxl, image_flux, image_sdxl_session, image_flux_session, session_poc
│   ├── data/registry/            models.json (31), endpoints.json (47), providers.json (15), image_presets.json — data, not code
│   └── tests/                    57 test files + conftest.py + fake_drive.py (762 test functions by static count)
├── frontend/
│   ├── Dockerfile, package.json, vite.config.ts, tsconfig*.json, index.html, .env.example, .env.production
│   ├── public/                   favicon.svg, fonts/*.woff2
│   └── src/
│       ├── main.tsx, App.tsx, index.css, types.ts
│       ├── api/client.ts         ALL fetch calls and the SSE parser (streamChat)
│       ├── contexts/             AuthContext.tsx, AppContext.tsx
│       ├── store/                useConversationStore.ts, conversationCache.ts, syncQueue.ts, ids.ts, deployedStore.ts
│       ├── crypto/               index.ts, session.ts (+ test): WebCrypto AES-GCM helpers (foundation only, unwired)
│       ├── hooks/useThemePreference.ts
│       ├── pages/                LandingPage, SignInPage, PrivacyPolicyPage, Layout, ChatPage, ProjectPage, ProjectsGalleryPage, ProvidersPage, SettingsPageWrapper, ImageLabPageWrapper
│       └── components/           ~45 components (chat, sidebar, image lab, settings, providers, dialogs, icons/)
├── workspace/                    Plans, decisions, status (dev-only; stripped from main)
│   ├── OVERVIEW.md (human), CODEBASE_MAP.md (this file), current_state.md, stable_commits.md, README.md (docs index)
│   ├── status/                   build_tracker.md, dev_log.md (long historical ledgers)
│   ├── archive/                  superseded long-form docs
│   ├── decisions/                change_log_2026.md (current), plus original design docs (some superseded)
│   ├── schemas/                  model_schema.md, provider_schema.md
│   ├── implemented_phases/       phase_01_0 … phase_13, F11, G1, Q1, plus plan_* retrospectives
│   └── plan/                     README, chat/, imageLab/, providers/, plan_findings.md (active plans)
├── .claude/                      Claude Code config: CLAUDE.md, AGENTS.md, settings.json (hooks), rules/*.md, agents/*.md (5), skills/{build-step,registry-refresh}
└── .gemini/                      GEMINI.md pointer to .claude/AGENTS.md
```

Untracked/ignored at the time of reading: `pawn_context.md` (untracked), local `.gitignore` edits, `secrets/*` (real values), `keys/`, `backups/`, `backend/data/{conversations,memory,checkpoints.db*}`, `node_modules/`, `dist/`, `__pycache__/`, `.venv/`.

---

## 4. Components and Modules

### 4.1 Backend — provider layer

**`core/normalize.py`** — public API (the only module routes/agents may use for LLM calls):

| Function | Behaviour |
|---|---|
| `chat_stream(model_id, messages, resolver, rate_limiter, on_provider_switch, user_id, on_model_switch)` | Async generator of text tokens. Two-level failover (below). |
| `chat_stream_with_tools(..., tools, tool_choice, ...)` | Async generator of `{"type":"content","delta"}` events then one `{"type":"done","tool_calls","finish_reason","usage"}`. The agent's execute loop uses only this. |
| `chat_complete(...)` | Non-streaming completion returning the message dict plus a `usage` key; same failover. Used for plan, verify, subagents, router fallback. |
| `chat_complete_single_model(...)` | One model's endpoints only, **no cross-model fallback** — exists because `fallback_models()` is not vision-filtered (used by the image-prompt enhancer). |

Failover internals: `_stream_one_model` iterates the model's keyed endpoints in priority order (`resolver.pick`). The call is recorded (`record_call`/`record_success`) when the first token arrives (or at end for a zero-token reply); token cost is recorded afterwards from the provider's `usage` chunk (`record_tokens`). A `ProviderError` of kind `rate_limit` calls `record_429`, anything else calls `record_connect_failure`. **Once any content token has been yielded, errors propagate instead of failing over.** If every endpoint fails before any token, `_ModelExhausted` is raised and the outer function moves to the next model in `resolver.fallback_models(...)`, firing `on_model_switch`.

```python
except ProviderError as pe:
    last_error = pe
    if tokens_yielded > 0:
        raise pe
    if pe.kind == "rate_limit":
        rate_limiter.record_429(endpoint_id, user_id=user_id)
    else:
        rate_limiter.record_connect_failure(endpoint_id, user_id=user_id)
```

**`core/llm_core.py`** — `chat_complete`, `stream_llm`, `stream_chat_with_tools`, `close_client`, `_detect_provider(url)` (returns `"anthropic"` if the host contains "anthropic", else `"openai_compatible"`), `_provider_headers`. Streams parse `data: ` SSE lines; tool-call deltas are accumulated by `index` (id/type/name assigned, `arguments` concatenated, never parsed here). Requests ask for `stream_options.include_usage`. Error messages are sanitized (`_format_upstream_error`): 401 → "API key rejected…", 429 → "Rate limit reached…", ≥500 → generic. Upstream response bodies are never forwarded.

**`resolver/resolver.py`** — `Resolver(registry, rate_limiter)`:

- `pick(model_id, user_id)` → list of `(base_url, provider_model_id, headers, endpoint_id, provider, key_source)` for endpoints that are active, pass `rate_limiter.can_use`, have a usable key, and (for pool-sourced keys) pass `quota_share.enforce`. A provider name/alias passed as `model_id` selects all endpoints of that provider. Raises `NoEndpointError` with "Add your provider key in Settings…" when keyless.
- `_resolve_key_and_source(ep, user_id)` — key precedence by `ep.key_source`: `byok` (user key only), `pool` (operator key only), `either` (**BYOK first, pool fallback**; reversed from an earlier pool-first design on 2026-07-23).
- `rank_candidates(level, visibility, user_id, require_tools, require_vision, exclude_model_ids, task_type)` — ordering key `(tag_miss, quality_rank // QUALITY_TIE_BAND, best_headroom, recent_failures, model_id)`; see §7.
- `pick_model_by_capability(...)` → best model id or `NoEndpointError`.
- `fallback_models(model_id, user_id, task_type)` → requested model first, then same-level ranked models, then other levels (`research`, `balanced`, `fast`), de-duplicated.
- `usable_user_models`, `pick_by_capability`, `_has_usable_endpoint`, `_best_headroom`, `_recent_failures`.

Depends on `registry.loader.Registry`, `rate_limiter`, `llm_core`, `quota_share`, `key_store`, `config.read_pool_key`, `constants`, `registry.providers.PROVIDER_ALIASES`.

**`core/rate_limiter.py`** — `EndpointRateLimiter`, state keyed `(user_id, endpoint_id)`; unattributed calls use `usage_store.SHARED_USER` (`""`). Methods: `seed_from_store`, `can_use`, `record_call`, `record_tokens`, `record_429` (fixed 60 s cooldown), `record_connect_failure` (≥2 consecutive failures → 20 s cooldown), `record_success`, `failure_count`, `usage_pct` (max across dimensions), `snapshot`. `can_use` blocks at **90%** of rpm/rpd/tpm/tpd. rpm/tpm are 60 s in-memory windows; rpd/tpd are calendar-UTC-day counters mirrored to Postgres.

**`core/usage_store.py`** — `record`, `load_current`, `usage_for_user`, `usage_for_endpoint`; table `endpoint_usage`; a **persistence circuit breaker** disables writes after 3 consecutive failures (degrades to memory-only; `reset_failures()` re-arms).

**`core/quota_share.py`** — `enforce(ep, user_id, rate_limiter)` fail-open wrapper around `_enforce`; `registered_user_count()` (cached per UTC day); `DEFAULT_SATURATION_PCT = 80`.

**`core/key_store.py`** — encrypted BYOK keys in `user_api_keys` on `SHARED_DB_DSN`; 300 s in-process cache with explicit eviction; `prefetch(user_id)`, `get_key`, `set_key`, `delete_key`, `list_providers`, `has_search_key` (Tavily or Brave), Kaggle config (`get_kaggle`/`set_kaggle`/`delete_kaggle`/`has_kaggle_creds`, stored as encrypted JSON under provider `"kaggle"`).

**`core/pool_key_store.py`** — `pool_api_keys` table, 60 s cache, `set_pool_key`, `get_pool_key` (None if disabled), `get_pool_config`, `list_pool_providers`, `set_enabled`, `set_saturation_pct`, `delete_pool_key`.

**`config.read_pool_key(provider)`** — DB first (`pool_key_store`), Docker secret `pool_<provider>_api_key` as bootstrap fallback; the old `lru_cache` was removed so admin edits are live.

**`core/router.py`** — `classify(messages, has_doc, has_tools_likely, resolver, rate_limiter, user_id, has_search_key, has_kaggle_creds, has_image)` → `{difficulty: light|heavy, needs_agent, task_type}`; `resolve_final_model`. Heuristics detailed in §7.

**`core/drive_factory.py`** — `get_drive_for_user` (cache: 10 min live / 30 s "not linked", per-user build lock to prevent duplicate `PAWN` root folders), `require_drive_for_user` (raises `NotConfiguredError` → HTTP 412), `call_drive` (wraps any Drive failure into the same 412), `evict_user`.

### 4.2 Backend — agent

**`agent/graph.py`** (1087 lines). `AgentState` TypedDict fields: `messages, user_id, conversation_id, user_model_id, has_doc, has_tools_likely, scope_type, scope_id, has_image, image_b64, image_mime, mode_hint, difficulty, needs_agent, task_type, plan, tool_log, tokens_used, citations, final_answer, revision_count, needs_revision, verify_draft`.

Graph topology (`build_agent_graph`):

```text
classify ──needs_agent=False──▶ direct_answer ──▶ END
   │
   └─needs_agent=True──▶ plan ──▶ execute ──┬─heavy AND used web_search/fetch_url/delegate_researcher──▶ verify ──┬─gaps & budget left──▶ execute
                                            │                                                                    └─pass/accept──▶ END
                                            └─otherwise──▶ END
```

- `classify_node`: image attached → direct vision answer; `mode_hint` (`fast`/`pro`/`image`) short-circuits the router; otherwise `router.classify`.
- `direct_answer_node`: one streaming call, no tools. With an image it picks a vision-capable model (`ROLE_LEVELS["vision_answer"]`, `require_vision=True`) and builds a multimodal message for this turn only.
- `plan_node`: skipped for `difficulty == "light"`; otherwise one `chat_complete` with `tool_choice="none"`, at most 5 plan lines, emitted as a `step` event.
- `execute_node`: streaming tool loop (max `AGENT_MAX_ITERATIONS = 8`, token budget `AGENT_MAX_TOKENS = 24000`). Handles `delegate_*` tools via `run_subagent` (strictly sequential, depth 1), regular tools via `run_tool`, emits `step`, `tool_result`, `citation`, `memory_hit` events, and for **heavy** turns defers loop content and runs a mandatory **closing-synthesis** pass on the research tier (`resolve_final_model`). If research tools were used, the synthesis is buffered (not streamed) so the verifier can reject it unseen. `mode_hint == "image"` forces `tool_choice` to `generate_image` on the first iteration (or replies that Kaggle credentials are needed).
- `verify_node`: one research-tier check of the buffered draft against the original request + plan; `PASS` → dispatch draft as tokens; gaps → append a system nudge and loop back to `execute` up to `VERIFY_MAX_REVISIONS = 2`. Any failure accepts the draft.
- `DummyRateLimiter` / `DummyResolver` stand-ins exist for the no-dependency path (see §13 about `DummyResolver.pick` returning 5-tuples).

**`agent/subagents.py`** — presets `researcher` (tools: `fetch_url` + `web_search` if a search key exists; level `fast`), `summarizer` (no tools; `fast`), `coder` (no tools; `research`). Exposed to the orchestrator as `delegate_<name>(task)` tools; each runs at most `SUBAGENT_MAX_ITERATIONS = 5` iterations sharing the parent's token counter. A `delegate_*` call from inside a subagent returns `TOOL_ERROR` (max depth 1).

**`agent/tools/`** — `ToolContext(user_id, scope_type, scope_id, resolver, rate_limiter)`, `ToolSpec(name, description, parameters, handler)`. `registry.get_tools(ctx)`: always `calculator`, `get_datetime`, `fetch_url`; `web_search` iff Tavily/Brave key; `generate_image` iff Kaggle creds; `search_memory` + `doc_search` iff the chat has a memory scope. `run_tool` wraps every call in a 20 s timeout and converts exceptions into `TOOL_ERROR: …` strings.

| Tool | Notes |
|---|---|
| `calculator` | AST-whitelisted arithmetic (no `eval`), ≤200 chars, `**` exponent ≤1000, run in a thread |
| `get_datetime` | Current UTC ISO time |
| `fetch_url` | **SSRF guard**: http/https only, resolves host and rejects private/loopback/link-local/reserved/multicast/unspecified (incl. IPv4-mapped IPv6), manual redirects (≤3) re-guarded per hop; text via trafilatura, truncated to 8000 chars |
| `web_search` | Tavily first, else Brave; top 8 results; top 3 get full-body fetches (2000 chars each, concurrent, 10 s each) with snippet fallback |
| `search_memory` / `doc_search` | Hybrid retrieval limited to `match_kind="message"` / `"document"` within the chat's scope |
| `generate_image` | Fixed to SDXL, 30-minute warm session; reuses a live session or starts one; returns a job id immediately |

### 4.3 Backend — memory and storage

- **`memory/chunker.py`** — fixed 1600-char chunks (`400 tokens × 4`) with 200-char overlap; each chunk gets a UUID and the source `msg_index`.
- **`memory/embed.py`** — Gemini `gemini-embedding-2:embedContent` with `outputDimensionality: 768`; key is BYOK Google key first, then pool key; optional Ollama `nomic-embed-text` fallback (`PAWN_EMBED_BACKEND`, `PAWN_EMBED_FALLBACK_TO_OLLAMA`, `PAWN_OLLAMA_URL`).
- **`memory/index.py`** — `add_chunk` upsert into `memory_chunks` (conflict on `(user_id, chunk_id)`), exception-safe.
- **`memory/indexer.py`** — `resolve_scope` (5-minute in-process cache; scope derived from Drive folder placement), `index_turn_task`, `index_document_task`, `rebuild_index`, `evict_scope`. **Drive first, Postgres second**: chunks are appended to the chat's `rag_chunks.jsonl` before any Postgres write; Postgres is a rebuildable derived index.
- **`memory/retrieve.py`** — vector candidates (`match_scoped_chunks`) + FTS candidates (`search_scoped_chunks`), fused with RRF `1/(60+rank)`; degrades to FTS-only if embedding fails and to `[]` if Postgres is down.
- **`memory/summarize.py`** — fast-tier bullet summary (≤150 words) written to `summary.md`, then re-indexed through `index_turn_task`; triggered every 20 messages.
- **`memory/locks.py`** — per-`(user, conv)` `asyncio.Lock` shared by indexing, document upload and chat moves.
- **`storage/drive.py`** — `DriveStorage`: Drive v3 wrapper with RLock-guarded shared transport, folder/file-ID caches (reads by ID are strongly consistent), 20 s socket timeout, deterministic oldest-first root selection (duplicate `PAWN` roots are logged), `read_files_in_folders` (8-way thread fan-out for listing), `move_item`, `delete_file`.
- **`storage/conversations_drive.py`** — chat CRUD; folder placement defines scope (`chats/{id}` standalone vs `projects/{pid}/{id}`); one-time legacy-layout migration; `append_messages` and `append_rag_chunks` are download-append-reupload.
- **`storage/projects_drive.py`**, **`storage/documents_drive.py`** — project CRUD / chat moves; `uploads/{doc_id}.txt`.

### 4.4 Backend — images

- **`core/image_models.py`** — frozen `ImageModel` dataclass per model (`sdxl`, `flux`): kernel slug (env-suffixed with `-dev` outside prod), template paths, Kaggle dataset, accelerator `NvidiaTeslaT4`, six native resolution buckets (1:1, 3:4, 4:5, 4:3, 16:9, 9:16), scheduler note, default negative prompt (SDXL only), per-model warm-up detection thresholds (FLUX: 300 s heartbeat-stale / 600 s no-heartbeat / 1500 s startup), and a `PromptSchema` for the enhancer.
- **`core/image_session.py`** — session lifecycle (`start_session`, `extend_session`, `stop_session`, `get_session_status`), job layer (`submit_session_job`, `create_cold_job`, `run_cold_job`, `spawn_cold_job_bg`, `get_job`, `list_jobs`, `delete_job`, `reorder_queue`, `reap_stale_jobs`), and `ImageJobParams`. Detailed in §5.4.
- **`core/kaggle.py`** — HTTP client for `https://www.kaggle.com/api/v1`; `KGAT_…` tokens use Bearer, classic keys use Basic; `inject_payload` base64-encodes the payload into the `__PAWN_PAYLOAD_B64__` placeholder; `deploy_kernel` (single non-blocking push; HTTP 409 treated as "already exists"), `run_kernel` (wait idle → push → poll → download `out.png`), `kernel_status` (best-effort probe).
- **`core/vision_enhance.py`** — rewrites short/vague prompts into the target model's preferred shape using a vision-capable model; never raises.

### 4.5 Frontend modules

| Module | Responsibility |
|---|---|
| `api/client.ts` (852 lines) | Every network call; `streamChat()` SSE parser with typed callbacks; `handle401` (clears token and reloads); `PermanentSyncError`; `AUTO_MODEL_ID`/`resolveModelId`; types for registry, dashboard, jobs, projects |
| `contexts/AuthContext.tsx` | Token/user in `localStorage` (`pawn-token`, `pawn-user`); OAuth callback parsing (`?token&user&generated_password`); `login`, `loginWithPassword`, `logout`, `updateUser` |
| `contexts/AppContext.tsx` | Theme, registry models/providers, configured providers, user prefs (display name, default model, bubble colors, background effect) |
| `store/useConversationStore.ts` | Single owner of conversation/project lists, messages, active selection, drafts, streaming flags; optimistic mutators |
| `store/syncQueue.ts` | Persisted, de-duplicating, exponential-backoff queue of create/rename/delete/project/move ops |
| `store/conversationCache.ts` | Per-user `localStorage` cache (LRU 30 chats, ~4 MB ceiling, debounced 300 ms) and `mergeServerMeta`/`mergeServerProjects` reconciliation |
| `crypto/` | PBKDF2(600k)+AES-GCM helpers, per-tab key session. Salt endpoint exists, but nothing in the app calls these for stored data (see §13) |
| `pages/ChatPage.tsx` | Streaming orchestration, per-conversation `AbortController`s, trace/segment building, attachments, rate-limit countdown |
| `components/Message.tsx`, `TraceView.tsx` | Markdown rendering; interleaved text/tool segments; collapsible trace groups; citation chips; inline image-job chips |
| `components/ImageLabPage.tsx`, `ImageGenerator.tsx`, `GenerationsPanel.tsx`, `AdvancedParams.tsx`, `advancedParamsConfig.ts` | Image Lab: per-model session controls, advanced params (per-model config classes), job monitor with reorder/edit/refine/delete |
| `components/ApiKeysSection.tsx`, `PoolKeysSection.tsx`, `ProvidersPage.tsx` | BYOK key management, admin pool keys, free-tier dashboard (Models / Providers (BYOK) / Admin tabs) |
| `components/Sidebar.tsx` + `Project*`, `KebabMenu`, `SearchResults` | Navigation, chats, projects, memory actions |

---

## 5. Data Flow and Architecture

### 5.1 Login and session

1. SPA calls `GET /auth/login`; the backend builds a Google OAuth `Flow` (confidential client, **PKCE disabled** because the flow is stateless across two requests, scopes `openid`, `userinfo.email`, `userinfo.profile`, `drive.file`, `access_type=offline`, `prompt=consent`) and returns `auth_url`.
2. Google redirects to `GET /auth/callback?code=…`. The backend exchanges the code (with `OAUTHLIB_RELAX_TOKEN_SCOPE=1` so granular-consent scope reordering does not error), reads the Google profile, and upserts `users`. A random 16-char password is generated and Argon2id-hashed on every callback, but only persisted on a **true first insert** (`returning (xmax = 0) as inserted`). Access and refresh tokens are AES-GCM encrypted into `user_drive_tokens`; the cached `DriveStorage` is evicted; a 7-day HS256 JWT is issued.
3. The backend redirects to `{FRONTEND_URL}/?token=…&user=<json>` (plus `&generated_password=…` for new users only). `AuthContext` stores token/user in `localStorage`, shows `GeneratedPasswordModal` once, and strips the query string with `history.replaceState`.
4. Alternative: `POST /auth/login-password` (generic 401 for unknown email or wrong password; 8 failures per `(ip, email)` within 15 minutes → 429).
5. Every non-public request carries `Authorization: Bearer <jwt>`; `AuthMiddleware` sets `request.state.user_id` and `.email`. Public prefixes: `/health`, `/auth/`.

### 5.2 A chat turn (`POST /chat`)

1. SPA `streamChat()` posts `{messages, model_id?, doc_id?, conversation_id, image_b64?, image_mime?, mode_hint?}`. `model_id` is omitted when the user chose "Auto".
2. Route: loads the conversation bundle (meta + last 10 messages + `summary.md`) from Drive on a thread pool (lazily creating the conversation if the client-owned id does not yet exist), prefetches the user's keys, resolves the memory scope, and builds the graph `inputs`. Thread id is `"{user_id}:{conversation_id}"` for the SQLite checkpointer.
3. `graph.astream_events(...)` drives the agent. Nodes emit LangChain *custom events*; the route translates them to SSE through `events.py` builders (`token`, `step`, `tool_result`, `memory_hit`, `model_call`, `provider_switch`, `citation`, plus an internal `final_provider` used to fill `done.via_provider`).
4. `done` is emitted. Only afterwards, if the turn succeeded: the user+assistant messages (with a `trace` of tool calls and `citations` read back from the checkpointed state) are appended to `messages.jsonl`, and **background tasks** are scheduled: `index_turn_task` (chunk → Drive `rag_chunks.jsonl` → embed → Postgres), `auto_title_background_task` (when the title is still "New Chat" and `message_count == 2`), and `summarize_conversation_task` (when `message_count >= 20 and % 20 == 0`).
5. In the browser each SSE event updates the in-flight assistant message in `useConversationStore` (`trace`, `segments`, `citations`, `content`). On `done` the client bumps the conversation, schedules a debounced title refresh, and—if a tool was used—fetches the persisted trace to back-fill tool `observation`s.

### 5.3 Memory read path

`search_memory`/`doc_search` → `retrieve(query, user_id, scope_type, scope_id, match_kind)` → embed the query (BYOK Google key, else pool key) → SQL `match_scoped_chunks` (cosine) and `search_scoped_chunks` (FTS) → RRF → top 4. Results are formatted as `- [conv:<id>] <text>` so the execute loop can emit one `memory_hit` SSE event per hit with provenance.

### 5.4 Image generation

**Warm session path (default in Image Lab and for the chat tool):**

1. `POST /generate/session/start` → `start_session`: validates model, requires Kaggle credentials and `POSTGREST_PUBLIC_URL`; in one transaction marks prior live sessions for `(user, model)` as `ended` and inserts an `image_sessions` row (`status='starting'`, random `session_token`, `expires_at`); builds the payload `{session_id, postgrest_url, session_token, model, expires_at, poll_interval, max_images}`, injects it base64-encoded into the session notebook, and pushes it to the user's Kaggle account (`enableGpu`, internet on, dataset mounted, `machineShape` = accelerator).
2. The kernel (cell 0) starts a **supervisor thread** that heartbeats every poll and hard-exits on `stopping`/`ended`/expiry, or after 600 s with no successful PostgREST contact. It then PATCHes `installing` → `loading_model` → `ready`.
3. `POST /generate/session/job` → `submit_session_job` inserts an `image_jobs` row (`queued`) after snapping width/height to a native bucket and prepending the model's default negative prompt (skipped for non-photoreal style presets). Prompt enhancement and style/subject suffixes are applied by the route before insertion.
4. The serve loop picks `status=eq.queued` ordered by `queue_pos.asc.nullslast,created_at.asc`, runs the pipeline (txt2img, or img2img via `from_pipe`/`FluxImg2ImgPipeline`), and PATCHes `done` with the PNG base64.
5. The browser polls `GET /generate/jobs` (3 s) and `GET /generate/session/status`; `get_session_status` actively detects dead kernels (heartbeat staleness, Kaggle status probe, startup timeout, stop grace of 30 s) and writes `error` status; `list_jobs` calls `reap_stale_jobs` to fail orphaned jobs.

**Cold path:** `POST /generate` with `modality=image` creates (or de-duplicates to) a `queued` cold job (`session_id` NULL) and spawns a GC-safe background task that runs `generate.generate_image` → `kaggle.run_kernel` (push, poll, download `out.png`); the frontend polls the job.

**Security design:** the notebook only ever receives the PostgREST public URL and a per-session token. Postgres RLS policies for the restricted `pawn_anon` role permit access only where `image_sessions.session_token` matches the `X-Session-Token` request header.

### 5.5 Optimistic UI and sync

The conversation id is generated client-side (`crypto.randomUUID`). "New chat" creates a frontend-only draft (no sidebar row, no network). First send calls `promoteDraft` and the chat route lazy-creates the Drive conversation. Rename/delete/project ops are applied locally and enqueued; `SyncQueue` persists to `localStorage`, retries with exponential backoff (cap 30 s), drains on `online`, collapses redundant ops, and drops ops that keep returning a permanent 404 after 3 attempts.

---

## 6. APIs and Interfaces

All routes require a Bearer JWT except `/health` and `/auth/*`. Errors: `ProviderError` → 429 (rate_limit) or 502 as `{"error": msg}`; `NoEndpointError` → 503; `NotConfiguredError` → 412 `{"detail","code":"not_configured"}`; `KaggleError` → 502 `code:"kaggle"`; `UnknownModelError` → 400.

| Method & path | Body / params | Response | Purpose |
|---|---|---|---|
| `GET /health` | – | `{"status":"ok"}` | Liveness (public) |
| `GET /auth/login` | – | `{auth_url}` | Start Google OAuth (503 if not configured) |
| `GET /auth/callback` | `code` | 302 to frontend with `token`, `user` (+`generated_password` once) | Finish OAuth |
| `POST /auth/login-password` | `{email,password}` | `{token,user}` | Password login, rate-limited |
| `GET /auth/me` | Bearer | user row incl. `is_admin`, `password_changed` | Profile (never returns `password_hash`) |
| `GET /auth/drive/status` | Bearer | `{connected}` | Proves `drive.file` works via a real Drive call |
| `POST /auth/logout` | – | `{ok:true}` | Stateless |
| `PUT /account/password` | `{new_password}` (≥8 chars) | `{status:"ok"}` | Set password; no current-password check by design |
| `POST /chat` | see §5.2 | `text/event-stream` | Agent chat |
| `GET/POST /conversations` | POST `{id?,title,model_id}` (idempotent on `id`) | list / meta | List all (standalone+project, tagged `project_id`) / create |
| `GET/PATCH/DELETE /conversations/{id}` | PATCH `{title}` | `{meta,messages}` / meta / `{status}` | Detail / rename / delete (also deletes `memory_chunks`) |
| `POST /upload` | multipart `file` (.pdf/.txt), `conversation_id?` | `{doc_id,filename,char_count}` | Store in Drive `uploads/`, index into chat scope in background |
| `GET /crypto/salt` | – | `{salt}` | Per-user PBKDF2 salt in `PAWN/.salt` (foundation for client-side encryption) |
| `GET /registry/models` | – | list of `{model_id,display_name,capability_level,capability_tags,context_window,endpoint_count,providers}` | User-facing models |
| `GET /registry/providers` | – | provider entries | Single source of truth for providers |
| `GET /keys` | – | `{providers:[…]}` | Providers the user has keys for (names only) |
| `PUT/DELETE /keys/{provider}` | `{api_key}` | `{status,provider}` | Store/delete encrypted BYOK key (validated against provider registry) |
| `GET/PUT/DELETE /keys/kaggle` | PUT `{username,api_token}` | `{has_creds,kernels}` / ok | Kaggle credentials (token never returned) |
| `GET /dashboard/free-tiers` | – | `{total_tokens_remaining_today, rows[], uncapped_providers[]}` | Per-user free-tier budget; rows carry `key_source`, `available_via_byok/pool`, rpm/rpd/tpm/tpd used+limit, `fair_share_remaining` |
| `GET/PUT/DELETE/PATCH /admin/pool-keys[/{provider}]` | PUT `{api_key}`; PATCH `{enabled?,saturation_pct?}` | metadata only (never keys) | Admin-only (403 unless email == `ADMIN_EMAIL`) |
| `GET /admin/stats` | – | `{registered_users}` | Admin |
| `POST/GET /projects` | `{id?,name,description}` | project / list with `chat_count` | Projects |
| `PATCH/DELETE /projects/{id}` | `{name?,description?}` | project / ok | Rename-edit / cascade delete (holds all contained chats' locks) |
| `POST/DELETE /projects/{id}/chats/{conv_id}` | – | `{status}` | Move chat into/out of project (Drive first, then `memory_chunks` scope, then scope-cache eviction) |
| `POST /memory/rebuild`, `POST /memory/clear` | `{scope_type:"chat"|"project", scope_id}` | `{chunks_indexed}` / ok | Re-derive or wipe a scope's memory |
| `POST /generate/connect` | `{model}` | ok | Push the cold notebook to verify credentials |
| `POST /generate` | `{modality:"image", prompt, model, params, init_image_b64|init_job_id, enhance_prompt}` (`modality:"cube"` is a POC) | `{job_id,status}` | Cold image job |
| `GET /generate/jobs` | `model?`, `limit` | job summaries (no image bytes) | Monitor list (also reaps stale jobs) |
| `POST /generate/session/start|stop|extend`, `GET /generate/session/status`, `POST /generate/session/job` | see §5.4 | status / ids | Warm session control |
| `GET/DELETE /generate/job/{id}`, `POST /generate/jobs/reorder` | reorder `{session_id,job_ids}` | job / ok / 409 | Fetch with image bytes, delete (not while running), reorder queue |

**SSE event types** (`events.py`): `token{delta}`, `done{via_provider,via_endpoint_id}`, `error{message,code?}`, rate-limit error with `retry_after`, `provider_switch{from,to}`, `step{label,detail,agent}`, `tool_result{name,observation,agent}`, `memory_hit{summary,scope,source_conv_id}`, `model_call{model,purpose}`, `citation{url,title}`. `README.md` lists only 7 types; the code has 10 builders.

**Internal interfaces.** `normalize.*` (LLM calls), `Resolver.pick`/`rank_candidates`, `EndpointRateLimiter` methods, `ToolSpec.handler(args, ctx) -> str`, `drive_factory.require_drive_for_user` + `call_drive`, `postgres_client.fetchone/fetchall/execute/transaction`, `kaggle.deploy_kernel/run_kernel`, and the PostgREST protocol between the backend DB layer and the Kaggle kernels (tables `image_sessions` and `image_jobs`).

**Kaggle kernel ↔ PostgREST contract.** Headers `Content-Type: application/json`, `X-Session-Token: <token>`, `Prefer: return=representation` on PATCH; reads `image_sessions?id=eq.<id>`, `image_jobs?session_id=eq.<id>&status=eq.queued&order=queue_pos.asc.nullslast,created_at.asc&limit=1`; writes status/heartbeat/images.

---

## 7. Core Logic and Algorithms

The routing, failover, quota, retrieval and agent logic is below.

### 7.1 Model selection (capability-first routing)

- Registry: **31 models** in `models.json` (28 active; 11 fast / 7 balanced / 11 research; 8 active vision-capable; 2 embedding models of which one, `gemini-embedding-2`, is active) and **47 endpoints** (38 active) across 11 chat providers, every endpoint `key_source: "either"`.
- `ROLE_LEVELS` maps internal roles to capability levels (orchestrator `balanced`; final_light `fast`; final_heavy `research`; summarizer/titler `fast`; subagents researcher `fast`, coder `research`, summarizer `fast`; vision roles `balanced`). `ROLE_TASK_TYPES` is a parallel dict of task types.
- `rank_candidates`: hard filters (level, `require_tools`, `require_vision`, excluded ids, at least one reachable keyed endpoint) then sort by:

```python
def sort_key(m: ModelEntry):
    tag_miss = 0 if (wanted_tags and wanted_tags & set(m.capability_tags)) else 1
    band = m.quality_rank // QUALITY_TIE_BAND          # QUALITY_TIE_BAND = 10
    return (tag_miss, band, self._best_headroom(m.id, user_id),
            self._recent_failures(m.id, user_id), m.id)
```

  Task type is a **preference**, vision/tools are **hard** filters. Quality ranks are curated sparse integers (lower is better; default 999 so an uncurated model never outranks a curated one). The user's explicit model pick always wins for the final answer; "Auto" omits `model_id`.

### 7.2 Router heuristics (`core/router.py`)

- `difficulty`: heavy if text > 1500 chars, contains a code fence, any of the `_HEAVY_KEYWORDS` (plan, analyze, debug, prove, compare, research, step by step, why), a doc is attached, or the previous assistant turn used tools; light if < 200 chars; the 200–1500 band calls one `chat_complete` ("light or heavy") and defaults to heavy/agent on any failure.
- `needs_agent`: heavy, or a URL present, or (search key present and time-sensitive keywords), or (Kaggle creds and image-generation phrases), or memory-recall phrases.
- `task_type`: image → `vision`; code fence or coding keyword → `coding`; summarization keywords → `summarization`; reasoning keywords → `reasoning`; else `general`.
- Composer `mode_hint`: `fast` = direct answer (except explicit image requests when Kaggle is connected), `pro` = full agent, `image` = forced `generate_image`.

### 7.3 Failover and quota

- Soft block at 90% of any published rpm/rpd/tpm/tpd; `record_429` → 60 s cooldown (the provider's `Retry-After` is not read); two consecutive non-429 failures → 20 s dead-host cooldown; `usage_pct` is the max across dimensions; day counters reset at UTC midnight and are re-seeded from Postgres at startup.
- Token accounting uses the provider's own `usage`; unknown is recorded as 0 and never estimated.

### 7.4 Pool fair-share (`quota_share._enforce`)

For each of `tpd_limit` (tokens) and `rpd_limit` (requests) that the endpoint publishes: block if the pool-wide total (the `SHARED_USER` aggregate row) has reached the limit; compute `is_strict = shared_total / limit >= saturation_pct/100` (default 80, per-provider override); in strict mode block when this user's own consumption ≥ `limit / N` where N is the registered-user count. Any exception allows the call.

### 7.5 Agent loop control

Iteration cap 8, token cap 24 000, per-tool timeout 20 s, subagent cap 5 iterations, verify revisions ≤ 2, trace persisted capped to 50 entries. A budget-exhausted state appends a system nudge and proceeds to the final answer.

### 7.6 Retrieval

Chunking 400 tokens / 50 overlap (len/4 approximation); hybrid retrieval with candidate pool `max(20, top_k*4)`, RRF constant 60, `top_k = 4`; scope equality filter is the isolation guarantee (a chat only sees its own chunks, a project only its project's).

### 7.7 Image-prompt enhancement

`needs_enhancement`: skip only when the prompt has ≥25 words **and** contains camera/lighting vocabulary. The enhancer asks a vision-capable model (picked via `pick_model_by_capability(..., require_vision=True)`, two attempts) to rewrite into the target model's schema; the negative list is split on `negative prompt:`/`negative:`/`avoid:` markers.

---

## 8. Data Storage

### 8.1 Postgres (`postgres/schema.sql`)

Extensions: `vector`, `pgcrypto`. Tables:

| Table | Key columns | Notes |
|---|---|---|
| `users` | `user_id` (Google `sub`) PK, `email` unique, `name`, `picture`, `created_at`, `password_hash`, `password_changed` | |
| `user_drive_tokens` | `user_id` PK/FK, `access_token_enc`, `refresh_token_enc`, `expires_at` | AES-GCM encrypted |
| `user_api_keys` | PK `(user_id, provider)`, `key_enc`, `updated_at` | Also stores Kaggle JSON under provider `kaggle`; lives on `SHARED_DB_DSN` |
| `pool_api_keys` | `provider` PK, `key_enc`, `enabled`, `saturation_pct`, `updated_at` | Operator pool; lives on `SHARED_DB_DSN` |
| `memory_chunks` | `id` bigserial, `chunk_id` uuid, `user_id` FK, `scope_type` (`chat`/`project`), `scope_id`, `conv_id`, `kind` (`message`/`document`), `doc_id`, `msg_index`, `text`, `embedding vector(768)`, `fts_doc` generated tsvector, `created_at`; unique `(user_id, chunk_id)` | Indexes: ivfflat cosine (lists=10), GIN on `fts_doc`, btree `(user_id, scope_type, scope_id)`. **`schema.sql` drops and recreates this table**, so re-running it wipes memory |
| `image_sessions` | `id` uuid, `user_id`, `model`, `session_token`, `status` (`starting|installing|loading_model|ready|stopping|ended|error`), `expires_at`, `max_images`, `images_done`, `heartbeat_at`, `error`, `created_at`, `stop_requested_at` | RLS enabled |
| `image_jobs` | `id` uuid, `user_id`, `session_id` (NULL = cold job), `model`, `prompt`, `original_prompt`, `enhanced_prompt`, `status` (`queued|running|done|error`), `image_b64`, `mime`, `via`, `error`, `params jsonb`, `queue_pos`, `created_at`, `started_at`, `done_at` | RLS enabled; image bytes stored in-row as base64 |
| `endpoint_usage` | PK `(user_id, endpoint_id, window_kind, window_start)`, `requests`, `tokens`, `updated_at` | `user_id=''` is the shared-pool aggregate; no FK so history outlives accounts |

SQL functions: `match_scoped_chunks(query_embedding, user, scope_type, scope_id, kind, n)` and `search_scoped_chunks(query_text, …)` (both `language sql stable`), `pawn_current_session_token()`.

Roles/RLS: `pawn_anon` (NOLOGIN in `schema.sql`; `init_pawn_anon.sh` sets login + password from a Docker secret) with `select, insert, update` grants on the two image tables. Policies exist only for **select** and **update** (matching the session token header); there is no insert policy for `pawn_anon`.

Migrations (manual, `postgres/migrations/`): `G1_image_jobs_queue_pos`, `Q31_enhance_prompts`, `R2_endpoint_usage`, `doc_search_kind_return`, `image_sessions_stop_requested_at`, `memory_scoping`, `pool_api_keys`, `users_password`.

### 8.2 Google Drive layout (per user; root `PAWN/` in prod, `PAWN-dev/` otherwise)

```text
PAWN/
  .salt                                     PBKDF2 salt for the (unwired) client-side encryption
  conversations/
    chats/{conv_id}/        meta.json, messages.jsonl, summary.md, rag_chunks.jsonl
    projects/{project_id}/  project.json, {conv_id}/ (same shape as a standalone chat)
  uploads/{doc_id}.txt
```

`meta.json` carries `id,user_id,title,created_at,updated_at,model_id,message_count` and optional `attached_docs:[{doc_id,filename}]`. Assistant messages in `messages.jsonl` may include `trace` and `citations`. **Folder placement is the sole source of truth for scope**; there is no membership table.

### 8.3 Local files (`backend/data/`, bind-mounted at `/app/data`)

`registry/{models,endpoints,providers}.json` and `image_presets.json` (committed data); `checkpoints.db` (LangGraph SQLite checkpoints, ignored); `rate_limits/`, `memory/` (constants exist; ignored). `registry.seed.seed_registry()` writes `models.json`/`endpoints.json` from embedded `INITIAL_*` data only if missing (atomic temp-file + `os.replace`).

### 8.4 Browser storage

`localStorage` keys: `pawn-token`, `pawn-user`, `pawn-theme`, `pawn-display-name`, `pawn-default-model`, `pawn-user-bubble`, `pawn-ai-bubble`, `pawn-bg-effect`, `pawn-kaggle-deployed`, `pawn-cache:v1:<user>`, `pawn-syncq:v1:<user>`. In-memory only: the derived encryption key (`crypto/session.ts`).

### 8.5 In-process caches (backend)

BYOK keys (300 s), pool config (60 s), DriveStorage per user (600 s / 30 s), memory scope (300 s), registered-user count (per UTC day), Kaggle status probe (30 s per session), login failure deques, per-conversation and per-(user,model) asyncio locks (never evicted).

---

## 9. Configuration and Environment

Names only; no values.

**Docker secrets** (`/run/secrets/<name>`, read by `config.read_secret`, with an upper-cased env-var fallback for non-Docker runs): `postgres_dsn`, `shared_db_dsn` (optional), `encryption_secret` (64 hex chars = 32 bytes), `jwt_secret`, `google_client_id`, `google_client_secret`, `pool_<provider>_api_key` ×11 (optional bootstrap), plus compose-only: `postgres_password`, `postgrest_anon_password`, `postgrest_db_uri`, `pgrst_tunnel_key` and `keys_tunnel_key` (SSH keys from `keys/`).

**Environment variables:**

| Variable | Default | Purpose |
|---|---|---|
| `PAWN_ENV` | `dev` | `dev` → Drive root `PAWN-dev` and Kaggle slugs suffixed `-dev`; anything else → `PAWN`/unsuffixed. Prod `.env` must set `prod` |
| `PAWN_DATA_DIR` | `/app/data` | Root for registry/checkpoints (tests point it at a temp dir) |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:5174` | Comma list; `*` raises at import |
| `FRONTEND_URL` | `http://localhost:5174` | OAuth redirect target |
| `OAUTH_REDIRECT_URI` | `http://localhost:8001/auth/callback` | Must match the Google client |
| `CSP_CONNECT_SRC` | `http://localhost:8000` | Space-separated CSP `connect-src` extras |
| `POSTGREST_PUBLIC_URL` | empty | Public HTTPS URL injected into warm Kaggle sessions |
| `PAWN_EMBED_BACKEND`, `PAWN_EMBED_FALLBACK_TO_OLLAMA`, `PAWN_OLLAMA_URL` | `gemini`, unset, `http://localhost:11434` | Embedding backend |
| `OAUTHLIB_RELAX_TOKEN_SCOPE` | set to `1` by `routes/auth.py` | Tolerate scope reordering |
| `BACKEND_PORT`, `POSTGREST_PORT`, `COMPOSE_PROJECT_NAME` | per-env file | Prod compose only |
| `VITE_API_URL` | `http://localhost:8000` fallback in `client.ts`; compose dev sets `http://localhost:8001` | API base URL baked at build time (`frontend/.env.production` for prod) |

**Hardcoded config of note:** `ADMIN_EMAIL` constant in `constants.py` (admin = this single address). Middleware timeout 45 s with SSE paths `/chat` and `/generate` exempt. JWT lifetime 7 days (`jwt_utils`). Login limiter 8 failures / 15 min. Kaggle timeouts (run 600 s, poll 8 s, per-call 30 s, busy wait 300 s). Image session constants (heartbeat stale 90 s, startup 900 s, max duration 120 min, cold job wall-clock 1200 s).

**Config files:** `docker-compose*.yml`, `.env.*.example`, `backend/data/registry/*.json`, `.claude/settings.json` (tool permissions and hook scripts that block secrets writes/force-push), `frontend/tsconfig*.json`, `vite.config.ts` (only react + tailwind plugins; no proxy), `index.html` (inline theme bootstrap).

---

## 10. External Integrations

| Service | Used for | Where |
|---|---|---|
| Google OAuth2 / userinfo | Sign-in | `routes/auth.py` |
| Google Drive API v3 (`drive.file`) | All user content | `storage/drive.py` |
| Gemini (`generativelanguage.googleapis.com`) | Chat (OAI-compat endpoint) and `gemini-embedding-2:embedContent` (768-dim) | registry endpoints, `memory/embed.py` |
| Groq, Cerebras, Hugging Face router, GitHub Models (`models.inference.ai.azure.com`), OpenRouter, Mistral, NVIDIA NIM, SambaNova, Kluster, Zhipu | Chat completions | `data/registry/endpoints.json` |
| Tavily (`api.tavily.com/search`), Brave Search (`api.search.brave.com`) | `web_search` tool (user BYOK) | `agent/tools/web_search.py` |
| Arbitrary public web pages | `fetch_url` and search-result enrichment | SSRF-guarded |
| Kaggle REST API | Kernel push/status/output on the user's account | `core/kaggle.py` |
| Hugging Face / Kaggle datasets | SDXL weights (`steubk/stable-diffusion-xl-base-1-0`), FLUX weights (`guillaumegaillard/flux1-schnell-diffusers`), `madebyollin/sdxl-vae-fp16-fix` (pulled inside the kernel) | `image_models.py`, notebooks |
| Self-hosted PostgREST | Kaggle kernel rendezvous | compose, `schema.sql` |
| GCP, DuckDNS, Let's Encrypt/certbot, GitHub (deploy key) | Hosting, DNS, TLS, source | `deployment.md` |
| Ollama (optional) | Embedding fallback | `memory/embed.py` |
| OmniRoute (MIT) | Design inspiration only (no shared code); `quota_share.py` is a "faithful port" of its fair-share idea | README, `quota_share.py` |

---

## 11. Entry Points and Execution Flow

**Backend:** `uvicorn app.main:app --host 0.0.0.0 --port 8000` (image `CMD`; dev compose adds `--reload`). `main.py` imports routers, then `lifespan` enters `initialize_managers()`:

1. `CHECKPOINTS_DB.parent.mkdir`
2. `load_registry()` (seeds JSON if missing; builds `Registry`)
3. `EndpointRateLimiter()` + `seed_from_store()` (reload today's usage from Postgres; no-op when Postgres is down)
4. `Resolver(registry, rate_limiter)`
5. `AsyncSqliteSaver.from_conn_string(...)` → `build_agent_graph(resolver, rate_limiter).compile(checkpointer=…)`
6. Stored on `app.state` (`graph`, `checkpointer`, `registry`, `rate_limiter`, `resolver`). On shutdown `close_client()` closes the shared httpx client.

Import side effects worth knowing: `registry/providers.py` and `image_presets.py` load JSON at import time; `config.py` reads all secrets at import.

Middleware order as registered (Starlette runs the last-added outermost): `Auth` → `GZip(≥1000 B)` → `Timeout(45 s)` → `SecurityHeaders` → `CORS`. Routers: auth, chat, upload, conversations, registry, keys, generate, crypto, projects, memory, dashboard, admin, account.

**Frontend:** `main.tsx` → `App` → `AuthProvider` → `BrowserRouter`. Routes: public `/`, `/login`, `/privacy`; guarded (`RequireAuth` → `AuthedShell` = `AppContextProvider` + `GeneratedPasswordModal` + `Layout`): `/chat`, `/chat/:id`, `/projects`, `/project/:projectId`, `/project/:projectId/chat/:id`, `/imagelab`, `/providers`, `/settings`. `Layout` owns `useConversationStore` and passes it down via `Outlet` context. Dev: `npm run dev -- --host` (port 5173, mapped to 5174 on the host).

**Local stack:** `docker compose up` (backend 8001→8000, frontend 5174→5173, Postgres 127.0.0.1:5433, PostgREST internal). Optional `--profile tunnel up -d pgrst-tunnel` / `keys-tunnel` for remote Kaggle rendezvous and live key sharing with prod.

**Production:** `docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build` runs `backend` (500 MB, 0.5 CPU), `postgres` (200 MB, 0.3 CPU, no published port) and `postgrest` (128 MB, 0.1 CPU); backend/postgrest bound to loopback; host Nginx serves `frontend/dist` and proxies an allowlist of route prefixes plus `/pgrst/`.

**Release flow:** verify locally (pytest + `npm run build`) → `scripts/promote-to-main.sh` (merge dev→main, strip docs, refuse on non-doc conflicts, verify no doc leaks; does not push) → `git push origin main` → on the VM `git pull`, rebuild the frontend, `up -d --build`.

---

## 12. Testing

**Backend:** pytest + pytest-asyncio + pytest-xdist; 57 test modules (+ `conftest.py`, `fake_drive.py`); **762 `def test_` functions by static count** (docs cite 801 once parametrization is included). Largest suites: `test_image_session.py` (65), `test_agent.py` (63), `test_generate.py` (48), `test_agent_tools_search.py` (25), `test_router.py` (24), `test_image_jobs.py` (23), `test_capability_routing.py` (22), `test_pool_keys.py` (22).

Run: `docker compose exec backend pytest` (scoped), `docker compose exec backend pytest -n auto` (full suite), coverage `pytest --cov=app --cov-report=term-missing`; outside Docker `python -m pytest backend/tests/`.

Key conventions (from `conftest.py` and `.claude/rules/testing.md`):

- Provider calls are always mocked; no real network.
- `PAWN_DATA_DIR` is a fresh `mkdtemp` per pytest process/xdist worker, set **before** any `app` import, because parallel workers sharing a bind-mounted SQLite file broke `/chat` tests.
- Autouse fixtures: `bypass_auth` (patches `AuthMiddleware.dispatch` → `user_id="test-user-id"`), `stub_byok_key` (patches `key_store.get_key`), `stub_pool_keys` (patches `pool_key_store.get_pool_config` → `None`, skipped for `test_pool_key_store.py`).
- `FakeDriveStorage` is an in-memory folder/file tree that lets the real `conversations_drive`/`documents_drive` logic run in tests.
- Rate limiter tests monkeypatch `time.time()`.
- **Isolation gap:** the dev Postgres is not isolated; `rate_limiter.seed_from_store()` and pool-key reads have polluted tests before (the docs call for a per-test DB isolation pass).

**Frontend:** Vitest (`npm test` = `vitest run`); four test files exist in the tracked tree: `crypto/crypto.test.ts`, `components/AdvancedParams.test.ts`, `components/advancedParamsConfig.test.ts`, `components/GenerationsPanel.test.ts`. The documented gate is `docker compose exec frontend npm run build` (`tsc -b && vite build`) and `npx tsc --noEmit`. The README still says "no unit tests", which is outdated. There is no `jsdom`/`@testing-library` dependency in `package.json` even though the rules mention them, and no Playwright/E2E suite.

**Gate scoping (project rule):** backend-only diff → backend pytest only; frontend-only → `tsc` + build only; cross-stack gate only when SSE shapes, request/response models, or route paths change. CI: none in this repo (no `.github/` workflows).

---

## 13. Known Issues, TODOs, Incomplete Areas, Doc/Code Drift

**Marker search.** A search of `backend/app` and `frontend/src` for `TODO|FIXME|HACK|XXX` returned **no matches**. "Deferred" notes appear instead as prose:

- `backend/app/config.py:79` and `backend/app/core/image_session.py:22` — scoped per-session JWT auth for PostgREST is "deferred, mandatory before multi-user" (RLS by session token now partly addresses it).
- `deployment.md` §8 "Known deferrals": publicly reachable `/pgrst/` plus a **Published** OAuth consent screen; client-side encryption "foundation-only and unwired"; private/public repo mirroring guidance.
- `deployment.md` §12: the local-dev PostgREST tunnel (restricted key, `/pgrst-dev/` Nginx location) "has not been recreated on the new GCP VM" — local warm-session testing does not work until it is.
- `workspace/current_state.md`: Phase E.4 tunnel activation and E.5 verification deferred to the user; D.2 (signup-credit metadata) intentionally skipped; the Model schema (`workspace/schemas/model_schema.md`) is documented but **not implemented**; pre-existing accounts have no `password_hash` so the password nudge has nothing for them to change from.

**Things I observed in the code that look like defects or sharp edges** (reading only; none were executed):

1. `DummyResolver.pick` (in `agent/graph.py` and `memory/summarize.py`) returns **5-element** tuples, but `normalize.py` unpacks **6** (`…, provider, key_source`). It only matters on the "no resolver configured" fallback path.
2. `routes/chat.py` validates the model id against a hardcoded provider list `["google","gemini","cerebras","groq","huggingface","github","openrouter"]`, so a bare provider alias such as `mistral` would be rejected as unknown even though the resolver supports it.
3. The frontend countdown path (`onRateLimit`) is keyed on an SSE `error` with `code: "rate_limit"`, but `routes/chat.py` emits `events.error_event(exc.message)` without a code for `ProviderError`, and `events.rate_limit_event` is not used by the route I read — so the countdown looks effectively unreachable from the chat route.
4. `record_429` ignores the provider's `Retry-After`; the cooldown is a flat 60 s.
5. `_detect_provider` can return `"anthropic"` and set Anthropic headers, but all calls still go to `{base_url}/chat/completions` with an OpenAI-shaped payload; no Anthropic endpoint is in the registry.
6. `image_jobs` stores generated images (and `init_image_b64` inside `params`) as base64 in Postgres rows — heavy for a small VM RAM/disk budget. `list_jobs` omits bytes, but `get_job` returns them.
7. `postgres/schema.sql` runs `drop table if exists memory_chunks` — safe on a fresh volume, destructive if re-applied to a live database (init scripts only run on an empty volume; never run it by hand against prod).
8. `append_messages` / `append_rag_chunks` re-download and re-upload whole files; growth is bounded per chat but is O(n) per turn.
9. Module-level lock dictionaries (`routes/generate._locks`, `memory/locks._locks`, `image_session._cold_job_locks`) and `_probe_cache` are never evicted and assume a **single** uvicorn process.
10. JWT and `generated_password` travel in a redirect URL query string and the JWT lives in `localStorage` (XSS-reachable); the CSP allows `'unsafe-inline'` scripts. `requirements.txt` has no pins except LangGraph.
11. `ADMIN_EMAIL` is a hardcoded constant, not configuration.
12. `/generate` with `modality="cube"` is a transport proof-of-concept left in the public route; `session_poc` notebook is likewise a leftover.
13. `docker-compose.yml`'s `pgrst-tunnel` and `keys-tunnel` entrypoints hardcode `ubuntu@144.24.119.184`, the **terminated Oracle** VM's address (the GCP VM is `136.114.65.94` with user `pawndeploy`).
14. `components/PoolKeysSection.tsx` and `Layout.tsx` comments refer to an `AdminPage.tsx` that no longer exists (deleted in the 2026-07-23 Providers redesign).
15. `ImageLabPage.tsx`'s "Redeploy all" calls `connectKaggle` (the *cold* notebook slugs), while Generate goes through warm sessions — two parallel paths that must both stay valid, and the "connected" flag is only a `localStorage` boolean (`pawn-kaggle-deployed`).

**Documentation vs. code drift:** the README, `deployment.md`, `workspace/api_reference.md` (now deleted; section 6 here replaces it) and the decision docs were reconciled with the code on 2026-11-01. Still-open items:

- `.claude/settings.json` hooks block writes under `secrets/`; the PostToolUse hook that blocks edits to `llm_core.py`/`resolver.py` conflicts with the stated workflow of editing those files directly. Worth checking when automating.
- `workspace/decisions/architecture_details.md`, `agent_design.md` and `data_schemas.md` describe the ORIGINAL design (sqlite-vec RAG, JSON/ReAct agent, `text-embedding-004`). They carry a "superseded" banner; this file is authoritative for the as-built system.
- Prod runs without any `pool_*` Docker secrets (`docker-compose.prod.yml` mounts none); prod pool keys come only from the admin UI / `pool_api_keys` table.

---

## 14. Glossary

| Term | Meaning in this codebase |
|---|---|
| **BYOK** | Bring Your Own Key — each user stores their own provider keys (AES-GCM encrypted in Postgres) |
| **Pool / pool key** | Operator-owned shared key for a provider, a fallback for keyless users, governed by fair-share quota |
| **`key_source`** | Per endpoint: `byok`, `pool` or `either` (BYOK first). Also the returned *actual* source for a call |
| **Registry** | JSON data (`models.json`, `endpoints.json`, `providers.json`) describing models, endpoints and providers; "data, not code" |
| **Endpoint** | One provider's hosting of one model (base URL, provider model id, priority, rpm/rpd/tpm/tpd limits, active flag) |
| **Capability level** | `fast` / `balanced` / `research` tier of a model |
| **Task type** | `general` / `coding` / `reasoning` / `vision` / `summarization` — a *preference* axis orthogonal to level |
| **`quality_rank`** | Curated sparse integer within a level; lower is better; compared in bands of `QUALITY_TIE_BAND` (10) |
| **Headroom** | `1 − usage_pct` style live signal used to break ties between near-equal models |
| **Soft block (90%)** | `can_use` returns false at 90% of any published limit, before a real 429 |
| **Cooldown / dead host** | 60 s after a 429; 20 s after two consecutive connect failures |
| **`SHARED_USER`** | Empty-string user id used for unattributed usage and the pool aggregate in `endpoint_usage` |
| **Fair share / saturation** | Pool admission: generous below `saturation_pct` (default 80%), then each user is held to `limit / N` |
| **Draft chat** | Frontend-only unsaved chat; materialized on first send |
| **Scope** | Memory isolation unit: `('chat', conv_id)` or `('project', project_id)`; determined by Drive folder placement |
| **Project** | A Drive folder of chats sharing one memory scope |
| **RRF** | Reciprocal Rank Fusion, `Σ 1/(60+rank)`, merging vector and full-text rankings |
| **Trace / segments** | Persisted/live record of tool calls, steps, citations, memory hits; segments keep arrival order for interleaved rendering |
| **Mode hint** | Composer's Fast / Pro / Create Image selection sent as `mode_hint` |
| **Closing synthesis** | Mandatory final research-tier answer pass on heavy agent turns |
| **Verify / critic loop** | Post-synthesis plan-as-contract check (O.3) limited to 2 revisions |
| **Cold job / warm session** | One-shot Kaggle kernel run per image vs. a long-lived kernel serving a job queue |
| **Rendezvous (PostgREST)** | The shared table-based mailbox through which the backend and the Kaggle kernel communicate |
| **`pawn_anon`** | Restricted Postgres role used by PostgREST; row access gated by `X-Session-Token` RLS |
| **Heartbeat** | Kernel's periodic `heartbeat_at` PATCH; staleness (90 s by default) means a dead session |
| **Reaper** | `reap_stale_jobs`, which fails orphaned jobs on every `list_jobs` call |
| **`PAWN_ENV`** | Deployment label isolating Drive root and Kaggle slugs (`dev` vs `prod`) |
| **Phase letters** | Internal work-item labels used in comments: Phase A–O (agent/reply quality), M (memory scoping), W (warm sessions), Q (image quality), G (generations management), F (feature fixes), R (rate-limit/quota), "PAWN 2.0 Phase A–E" (pool, admin, fair share, isolation) |
| **Promote** | Merge `dev` into `main` with docs stripped via `scripts/promote-to-main.sh` |
| **Stable commits** | `workspace/stable_commits.md`; updated only when the user explicitly says so |

---
