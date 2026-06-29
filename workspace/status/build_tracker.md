# PAWN — Build Tracker

Source of truth for *what to build* is the relevant phase plan file in `workspace/plan/` or `workspace/implemented_phases/`.
This file tracks *where we are*. Update it after every step — mark `[x]` only when
tests pass and the step's demo works.

The Claude Code instance inside `/PAWN` uses this file to know what to build next.
Agents should read this before starting any work.

Legend: `[ ]` not started · `[~]` in progress · `[x]` done & verified

---

## Current Status

**Active phase:** Phase W — Warm Sessions + Job Tracking (imageLab branch)
**Active step:** W.1 — warm session backend + FLUX persistent notebook + unified job tracking
**Last completed:** W.0 (imageLab) — persistent Kaggle loop proof (CPU echo) + Supabase rendezvous; 117 backend tests green
**Branch:** imageLab (merges → dev)
**Plan:** `workspace/plan/plan_v5_warm_session.md`

> Phase MU (below) is code-complete on dev/main and live-verified (OAuth + Drive + BYOK).
> imageLab Milestones A.0/A.1 are tracked in `workspace/plan/plan_v4_kaggle_image.md`.

---

## Phase 1 — Foundation
*Plan reference: `workspace/implemented_phases/phase_1_foundation.md`*

- [x] **Step 1 — Create the repo**
  Folder structure, `.gitignore`, first commit. Demo: `git log` shows one commit.

- [x] **Step 2 — Claude Code config**
  `.claude/` wired: CLAUDE.md, rules, agents, skills, settings.json with hook.
  Demo: `claude` in the repo; rules load; hook blocks secret touches.

- [x] **Step 2.5 — Docker scaffolding**
  `constants.py`, `config.py`, `docker-compose.yml`, secrets pattern.
  Demo: `docker compose config` validates.

- [x] **Step 3 — Chat UI**
  React + Vite + TS + Tailwind. Components: ChatWindow, MessageInput, Message.
  Demo: type a message; it appears as a bubble.

- [x] **Step 4 — FastAPI backend**
  Health check, middleware stack (security headers, timeout, gzip).
  Demo: `curl http://localhost:8000/health` → `{"status":"ok"}`.

- [x] **Step 5 — Connect frontend to backend**
  `api/client.ts`, health check on mount.
  Demo: console logs `{status: ok}` from live backend.

- [x] **Step 6 — First real AI response**
  `llm_core.py` minimal, Gemini 2.5 Flash via OAI-compat endpoint.
  Demo: type "hello", get a real Gemini reply streaming.

- [x] **Step 7 — Typed SSE events**
  `events.py` builder functions. All event types wired. `StreamChatCallbacks` object in client.ts.
  Demo: Network tab shows `{"type": "token", "delta": "..."}`. 6 tests passing.

- [x] **Step 8 — Conversation history**
  Full message array forwarded per request.
  Test: `test_chat_forwards_full_history` verifies all turns reach the LLM. 7 tests passing.

- [x] **Step 9 — Multi-provider (normalize.py)**
  `core/normalize.py` with 6-provider PROVIDERS map (Groq, Cerebras, Gemini, HuggingFace, GitHub, OpenRouter).
  `chat.py` routes through normalize; accepts `provider` field in request.
  Groq secret added. 12 tests passing.

- [x] **Step 10 — Model switcher UI**
  Hardcoded dropdown, provider sent per message.
  Demo: switch mid-conversation, context intact.

- [x] **Step 11 — Basic RAG**
  `POST /upload`, whole-doc injection, attach button in UI.
  Demo: upload a doc, ask about it — AI answers from it.

---

## Phase 1.5 — Memory & Agent
*Plan reference: `workspace/implemented_phases/phase_1_5_memory_agent.md`*

- [x] **Step 12 — Multi-chat persistence**
  Backend source of truth. `data/conversations/<uuid>/`. CRUD endpoints. Sidebar UI.
  Demo: two chats with independent history, survive restarts. Auto-title fires.

- [x] **Step 13 — Complete typed SSE events**
  All event types dispatched and routed in `streamChat`. Frontend callbacks wired.
  Demo: all event types appear in Network tab; UI handles each.

- [x] **Step 14 — Per-chat memory summaries**
  Rolling `summary.md` per conversation. Threshold-triggered summarization.
  Demo: 30-message chat coherent; `summary.md` written to disk.

- [x] **Step 15 — RAG over memory**
  `data/memory/index.json`. `text-embedding-004` embed interface. Brute-force cosine.
  Demo: fact from chat A surfaces in chat B via retrieval.

- [x] **Step 16 — LangGraph agent**
  `StateGraph` with 5 nodes. JSON/ReAct protocol. Trace panel in UI.
  Demo: complex question → trace shows plan/retrieve/draft/critique/answer.

---

## Phase 1.6 — Rate-Limit Resilience
*Plan reference: `workspace/implemented_phases/phase_1_6_rate_limit.md`*
*Branch: `dev/rate-limit-resilience`*

- [x] **Step R1 — Registry foundation**
  `models.json` + `endpoints.json` seeded. `loader.py`. `GET /registry/models`.
  New secrets: huggingface, github, openrouter.
  Demo: `GET /registry/models` returns the full catalog.

- [x] **Step R2 — Rate limiter**
  `EndpointRateLimiter`: rolling windows, 90% threshold, cooldowns, dead-host.
  Demo: unit tests show endpoint flips unavailable at ≥90% and recovers.

- [x] **Step R3 — Resolver + normalize contract change**
  `Resolver.pick(model_id)`. `normalize.chat_stream(model_id, messages)`.
  `ChatRequest` takes `model_id` only. Agent swaps to `PURPOSE_TO_LEVEL`.
  Demo: force priority-1 past 90% → next endpoint serves reply; `provider_switch` emitted.

- [x] **Step R4 — Frontend wiring**
  `ModelSwitcher` fetches from API. `provider_switch` inline notice. Provider badge.
  Demo: dropdown shows Fast/Balanced/Research groups; failover notice appears.

- [x] **Step R5 — UI visual overhaul + LAN access**
  CSS variable theme system + FOUC-prevention script in `index.html`. `InteractiveGridBackground` canvas. Floating pill header islands (title toggle left, ModelSwitcher + dark mode right); gradient overlays `h-16`. Smart scroll. `TracePanel.tsx` deleted — trace inlined in `Message.tsx` as unified metadata row + collapsible step cards. `react-markdown` for assistant. Auto-resize pill→card input. `Sidebar` mini `w-12`, click-column expand, flicker-free transitions, profile avatar, neutral delete. Registry `providers` field. LAN IP in CORS + `VITE_API_URL`.
  Demo: dark/light persists on reload (no flash); long message collapses; agent trace auto-collapses after stream; grid reacts to mouse.

- [x] **Merge Phase 1.6 → main**

---

## Phase MU — Multi-User / Auth / BYOK / Drive
*Plan reference: `~/.claude/plans/what-i-want-1-mutable-waffle.md`*
*Branch: dev*

Architecture:
- App data (profiles, sessions, BYOK keys, memory embeddings) → Supabase free tier (pgvector)
- User data (conversations, uploads) → user's own Google Drive
- Auth: Google OAuth2 (includes drive.file scope)
- BYOK: keys encrypted AES-256-GCM at rest; backend proxies all LLM calls (no CORS exposure)

- [x] **MA-1** — Supabase client + AES-GCM crypto + new secrets wired ✓
  `backend/app/db/supabase_client.py`, `backend/app/core/crypto.py`, 6 new secrets,
  updated `config.py`, `requirements.txt`, `docker-compose.yml`, `secrets/*.example`
  NOTE: supabase_url / supabase_service_key / google_client_id / google_client_secret
  contain PLACEHOLDER values — user must fill with real values before MA-2 routes work.
  encryption_secret and jwt_secret are pre-generated with real random values.

- [x] **MA-2** — Google OAuth2 + auth routes + JWT ✓
  `backend/app/core/jwt_utils.py`, `backend/app/routes/auth.py` (login/callback/me/logout),
  registered in main.py. /auth/* routes public (no middleware yet).

- [x] **MA-3** — Auth middleware + route scoping ✓
  `backend/app/middleware/auth.py` (AuthMiddleware, JWT Bearer, public /health /auth/*),
  `backend/tests/conftest.py` (bypass_auth fixture for tests),
  storage/conversations.py and documents.py scoped by user_id,
  routes/conversations.py, routes/upload.py, routes/chat.py pass user_id through,
  LangGraph thread_id namespaced as {user_id}:{conv_id}. 47 tests passing.
  `backend/app/routes/auth.py` (login/callback/me/logout), `backend/app/core/jwt_utils.py`

- [x] **MA-4** — Frontend auth UI + 429 back-off timer ✓
  `frontend/src/contexts/AuthContext.tsx` (AuthProvider, useAuth, OAuth callback handler),
  `frontend/src/pages/LoginPage.tsx` (Google sign-in button with inline SVG logo),
  `frontend/src/api/client.ts` (authHeaders() on all requests, onRateLimit callback, 401 auto-reload),
  `frontend/src/App.tsx` (AuthProvider wrapper, AuthGate, 429 countdown banner, useAuth for displayName),
  `backend/app/events.py` (rate_limit_event + code field on error_event).
  Build passes (tsc + vite). 47 backend tests passing.
  `AuthContext.tsx`, `LoginPage.tsx`, JWT header injection in `client.ts`, rate-limit countdown UI

- [x] **DD-1** — Drive storage layer ✓
  `backend/app/storage/drive.py` (DriveStorage: root/folder CRUD, upload/download text,
  list, delete, find; auto token refresh + Supabase persistence callback),
  `backend/app/core/drive_factory.py` (get_drive_for_user — exception-safe, returns None
  when Supabase unavailable / no tokens / decrypt fails → callers fall back to local FS).

- [x] **DD-2** — Conversations → Google Drive ✓
  `backend/app/storage/conversations_drive.py` (same interface, drive as first param;
  folder structure PAWN/conversations/{conv_id}/meta.json|messages.jsonl|summary.md).
  Routes wired: routes/conversations.py + routes/chat.py + memory/summarize.py all try
  get_drive_for_user(user_id) first, fall back to local filesystem when None.

- [x] **DD-3** — Uploads → Google Drive ✓
  `backend/app/storage/documents_drive.py` (PAWN/uploads/{doc_id}.txt).
  Routes wired: routes/upload.py + routes/chat.py use drive when available, else local.
  47 tests passing (tests hit local fallback since no real Supabase).

- [x] **SM-1** — Memory → Supabase pgvector ✓
  `memory/index.py` add_chunk(user_id, conv_id, text, embedding) → Supabase insert (exception-safe).
  `memory/retrieve.py` retrieve(query, user_id, active_conv_id, top_k) → pgvector + FTS via RPC,
  RRF fusion in Python, graceful degradation (FTS-only if embed fails, [] if Supabase down).
  AgentState gains user_id; graph.py retrieve calls + chat.py inputs pass it through.
  summarize.py indexes summaries with user_id. Removed sqlite-vec dep.
  `supabase/schema.sql` created (tables + match_memory_chunks/search_memory_chunks RPCs).
  test_rag.py rewritten to mock Supabase. 47 tests passing.
  NOTE: user must run supabase/schema.sql in their Supabase project before memory works live.

- [x] **BK-1** — BYOK key store + /keys routes ✓
  `backend/app/core/key_store.py` (set_key/get_key/list_providers/delete_key, AES-GCM,
  exception-safe reads, VALID_PROVIDERS set). `backend/app/routes/keys.py`
  (GET /keys → providers only, PUT /keys/{provider}, DELETE /keys/{provider}; key values
  never returned). Registered in main.py. test_keys.py (7 tests).

- [x] **BK-2** — Resolver + normalize per-user key lookup ✓
  `resolver.pick(model_id, user_id=None)`: user BYOK key (key_store.get_key) preferred,
  falls back to shared Docker secret; keyed endpoints first, falls back to all available
  if none keyed (preserves test/dev path). `normalize.chat_stream(..., user_id=None)`
  forwards to pick. graph.py AgentState.user_id threaded into agent/ask_model/final nodes
  + their pick/chat_stream calls. chat.py generate_title + error fallback pass user_id.
  DummyResolver.pick signatures updated. 54 tests passing.

- [x] **BK-3** — Frontend settings panel ✓
  `frontend/src/components/ApiKeysSection.tsx` (BYOK: per-provider password input, Save/Remove,
  "Configured" badge, getKeys/setKey/deleteKey; key values never re-displayed).
  Integrated into existing `SettingsPage.tsx` (new API Keys section + Profile shows real email
  + Sign out button; removed now-implemented "Connected Accounts" from Future list).
  `Sidebar.tsx` profile card shows real email (gear icon already wired pre-MA-4).
  `App.tsx` passes user.email + logout; client.ts getKeys() unwraps {providers}.
  Fixed pre-existing unused-var build errors (useCallback, isAuthenticated).
  Frontend build passes (tsc + vite). 54 backend tests passing.

---

## Manual Setup (user action) — DONE: login working end-to-end ✓

Completed by user on 2026-06-27. Google OAuth2 → JWT → app login verified working.

1. **Supabase**: created free project; ran `supabase/schema.sql`; filled
   `secrets/supabase_url` + `secrets/supabase_service_key` (new-style `sb_secret_...` key).
2. **Google Cloud OAuth2**: created Web client; redirect URI
   `http://localhost:8001/auth/callback`; Drive API enabled; consent screen in Testing with
   test user added; filled `secrets/google_client_id` + `secrets/google_client_secret`.
3. `encryption_secret` + `jwt_secret` were already real (MA-1).

### Setup-time code fixes (must be committed)

- **PKCE disabled** (`autogenerate_code_verifier=False` in `routes/auth.py:_build_flow`): the flow
  is stateless (separate Flow objects in /login and /callback) so a per-request code_verifier
  can't survive; google-auth-oauthlib auto-PKCE caused "invalid_grant: Missing code verifier".
  Safe because this is a confidential client (has client_secret).
- **`OAUTHLIB_RELAX_TOKEN_SCOPE=1`** set at import in `routes/auth.py`: Google reorders/drops scopes
  (e.g. drive.file under granular consent), and oauthlib errors on any scope change. Relaxed so
  exchange completes; missing drive.file → app falls back to local filesystem storage.
- **Naive-UTC expiry fix** (`storage/drive.py` __init__): Supabase returns `expires_at` as tz-aware
  `timestamptz`, but google-auth compares expiry against a naive UTC now() → TypeError crashed every
  chat request. Now converted to naive UTC. This was the "conversations save but no reply" bug.

### Verified live (2026-06-27) ✓

- [x] Google OAuth login → JWT → app.
- [x] Conversations saving to user's Google Drive (`PAWN/conversations/`).
- [x] BYOK Google key (Settings → API Keys) → LLM reply streams back ("Hello there friend.").

### Still to verify (optional, before/after merge)

- [ ] Memory: fact from chat A surfaces in chat B (needs Supabase pgvector + embeddings).
- [ ] Second Google account → empty chat list (isolation).

### Next: commit setup fixes + merge dev → main

---

## Phase W — Warm Sessions + Job Tracking (imageLab)
*Plan reference: `workspace/plan/plan_v5_warm_session.md`*
*Branch: imageLab (merges → dev)*

Goal: keep one Kaggle container **warm** so repeat images are fast (user-set timer + image cap), and
make every generation a **durable, server-tracked job** (fixes the double-submit / lost-result bug)
surfaced in a **Generations monitor panel**. Architecture: **Supabase job-queue rendezvous** — a
persistent kernel loads the model once, then loops polling Supabase for prompts and writes images
back. Image Lab only (chat composer deferred to Milestone B). Targets the top deferred item
(FLUX ~820 s/image).

- [x] **W.0 — Prove the persistent loop (CPU, no model)** ⚠️ first / load-bearing ✓
  `image_sessions` + `image_jobs` schema; `kaggle_templates/session_poc/` CPU echo notebook;
  `core/image_session.py` (`start_session`/`get_session_status`/`stop_session`/`submit_session_job`/`get_job`)
  pushing via the non-blocking `kaggle.deploy_kernel`; session routes (`/generate/session/*`,
  `/generate/job/{id}`); new `supabase_anon_key` secret (public — service key never injected);
  minimal `SessionPocPanel` Lab control. 117 backend tests green (24 new); `npm run build` clean.
  code-reviewer + security-auditor PASS (0 critical). RLS/scoped-JWT deferred to W.1 (documented).
  **Live verify pending user setup:** run new schema in Supabase + add `secrets/supabase_anon_key`,
  then Lab → Start session → submit echo job → CPU kernel echoes it back, heartbeats, exits on Stop.

- [ ] **W.1 — Warm session backend + FLUX persistent notebook + unified job tracking**
  `image_flux_session/notebook.ipynb` (load once → serve loop); full session manager; **cold
  one-shot path retrofitted to a durable background job** (`POST /generate` → `{job_id}`,
  fire-and-forget worker, per-`(user,model)` de-dup); `GET /generate/job/{id}` + `/generate/jobs`;
  `supabase_jwt_secret` (scoped per-session JWT — service key never injected);
  `tests/test_image_session.py` + `tests/test_image_jobs.py`.
  Demo: cold Generate → refresh → job re-attaches in the panel and the result persists (bug fixed);
  warm FLUX session → first image ~10 min, later images in **seconds**. `pytest` green.

- [ ] **W.2 — Image Lab UI (session controls + Generations monitor panel)**
  Job-driven `ImageGenerator` (submit → poll job id); new `components/GenerationsPanel.tsx` (all jobs
  across models, status chips + thumbnails + view/download); session bar (duration/cap picker, live
  countdown, Extend, Stop, "session ended" CTA); **server-derived button state** (disabled while a
  model has an active job → no duplicate submit, survives refresh); `client.ts` job/session helpers.
  Demo: full warm-session flow + monitor panel live; `npm run build` clean.

---

## Working Agreement

- Auto mode: implement steps sequentially, update tracker after every step.
- Tests must pass before marking `[x]`. No exceptions.
- Update this file and `workspace/current_state.md` after every step.
- If blocked (user action needed), document in plan file and move to next implementable step.
