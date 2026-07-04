# PAWN — Build Tracker

Source of truth for *what to build* is the relevant phase plan file in `workspace/plan/` or `workspace/implemented_phases/`.
This file tracks *where we are*. Update it after every step — mark `[x]` only when
tests pass and the step's demo works.

The Claude Code instance inside `/PAWN` uses this file to know what to build next.
Agents should read this before starting any work.

Legend: `[ ]` not started · `[~]` in progress · `[x]` done & verified

---

## Current Status

**Active phases (merged track):** Phase 3 — WebCrypto Encryption (not started) + Phase D — Production Deployment (in progress, only D.8 remains, GATED) + Plan: Drive-Mandatory Storage (Phases 1-4 all DONE)
**Active step:** `plan_drive_mandatory.md` Phases 1-4 all done — Phase 4 (review/docs/commit) closed 2026-07-04: code-reviewer + security-auditor ran on the combined Phase 1-3 diff (a gap the plan called for but had never actually happened), both PASS with 4 WARN fixes applied (stale comment, missing error logging in `drive_factory.py`/`auth.py`, raw exception text leaking to clients in `upload.py`/`chat.py` genericized). 152 backend tests still green. **Deployment plan simplified 2026-07-04: dropped the two-environment staging-first deploy.** `dev` is now local-only, never deployed to the VM; only `main` deploys to prod (`pawnai.duckdns.org`) — D.6b (staging stack) is dropped, D.7/D.8 rewritten prod-only. Rationale: no public user base yet (Google OAuth consent screen is Testing-mode/allowlist-only), so D.6's local pre-deploy gate substitutes for a dedicated staging box. Local dev and prod **share one Google OAuth client** (both redirect URIs registered) and the same Google account for login; database/secrets stay **separate** per environment. Accepted tradeoff: local dev is x86, the VM is ARM64, so first-ever ARM issues surface at the real prod deploy. **Remaining before D.8:** strip the now-stale staging section out of `deployment.md` (currently still two-env text), then execute: promote `dev`→`main` → deploy to `/opt/pawn` → full verify (this is also where the Drive-linked OAuth happy path, untestable locally, finally gets exercised). **Env decisions:** `main`→prod (`pawnai.duckdns.org`), doc-free via promote script; BYOK keys stay in Postgres (not Drive); a known pre-existing gap (permissive `pawn_anon` RLS on image jobs, not scoped per-user) must close before ever flipping the OAuth consent screen from Testing to public. Phase 3 P3-1 encryption FOUNDATION complete (crypto module + backend salt endpoint + vitest) but its passphrase gate was removed from the auth flow (unwired to anything, pure friction — see plan_drive_mandatory.md). Full encrypt/decrypt-on-write wiring still DEFERRED pending a product decision (conflicts with server-side LLM/RAG/summarization — see implemented_phases/phase_8_encryption.md). Mobile readiness pass (all 7 fixes) complete.
**Last completed:** imageLab merged → dev; dev merged → main (2026-06-30). All Phase W, img2img (Plan 2), and Phase 6 UI work is on main. imageLab branch deleted.
**Branch:** dev (merges → main)
**Plans:** `workspace/implemented_phases/phase_8_encryption.md`, `workspace/plan/plan_deployment.md`

> All prior phases (MU, W, imageLab A.0/A.1, Phase 6 UI) are merged and live on main.
> imageLab Milestones A.0/A.1 are tracked in `workspace/implemented_phases/phase_5_kaggle_image.md`.

---

## Phase 1 — Foundation
*Plan reference: `workspace/implemented_phases/phase_1_0_foundation.md`*

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
*Plan reference: `workspace/implemented_phases/phase_5_kaggle_image.md`*
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
  **LIVE-VERIFIED (2026-06-29):** Lab → Start warm session → kernel reached Warm with a live
  countdown + fresh heartbeat, 2 echo jobs round-tripped through Supabase (ECHO: "really" rendered).
  Supabase's new sb_publishable_* key enforces RLS → added a permissive anon policy on the two
  tables (commit 043a7f3). The persistent-loop assumption is PROVEN.

- [x] **W.1 — Warm session backend + FLUX persistent notebook + unified job tracking** ✓
  `image_flux_session/notebook.ipynb` (load FLUX once → Supabase serve-loop); session manager made
  registry-driven (FLUX→GPU serve-loop, SDXL→CPU echo) + `extend_session`; **cold one-shot path
  retrofitted to a durable background job** (`POST /generate` → `{job_id}`, GC-safe fire-and-forget
  worker behind the per-`(user,model)` lock, de-dup); `GET /generate/jobs` (+ `/job/{id}` from W.0);
  constants (job poll, cold-job reap wall-clock); `reap_stale_jobs`. Frontend: `runGenerate`/poll
  contract, `extendSession`/`listJobs` helpers, `SessionPocPanel` renders PNG (FLUX) or echo (SDXL).
  132 backend tests (new `test_image_jobs.py`); `npm run build` clean. code-reviewer PASS (CRITICAL
  create_task-GC fixed) + security-auditor PASS (service key never injected).
  **Deferred (documented):** `supabase_jwt_secret` + scoped per-session JWT — the new Supabase
  `sb_publishable_*` platform deprecates legacy HS256-secret minting; permissive-anon RLS policy
  (W.0) kept for the single-user trial; **scoped JWT is MANDATORY before multi-user**. SDXL real
  serve-loop is a follow-up.
  **Live verify pending:** Image Lab → FLUX → Start warm session → first image ~10 min, later in
  **seconds**; Extend/Stop work; cold Generate still returns an image (now job-polled).

- [x] **W.2 — Image Lab UI (session controls + Generations monitor panel)** ✓
  Job-driven `ImageGenerator` (submit → poll job id, inline render); **server-derived button state**
  (parent lifts a shared `listJobs` poll → disabled while a model has a queued/running job → no
  duplicate submit, survives refresh; + a local submitting guard for the click→response window);
  new `components/GenerationsPanel.tsx` (all jobs across models/sessions, status chips, lazy
  thumbnails + View lightbox + Download); new `components/SessionBar.tsx` (duration/cap picker, live
  countdown, Extend +30, Stop, "session ended" CTA; re-attaches on refresh); `SessionPocPanel`
  deleted (superseded). `npm run build` clean; 132 backend tests green. code-reviewer PASS (0 critical;
  WARN fixes applied: double-submit guard, gated countdown ticker, mime-derived download filename).
  **Deferred (documented):** frontend unit tests (project has none — gate is `npm run build`);
  GenerationsPanel lazy-image fan-out capped at 30 (fine for trial).
  **Live verify pending:** full warm-FLUX flow + monitor panel; refresh mid-generate → job
  re-attaches in the panel + button stays disabled (the double-submit bug, visibly fixed).

- [x] **W.3 — Real SDXL warm serve-loop (image generation, not echo)** ✓
  *Plan: `workspace/implemented_phases/phase_5_kaggle_image.md`.* Added `kaggle_templates/image_sdxl_session/notebook.ipynb`
  (mirrors the FLUX serve-loop; loads SDXL once via `AutoPipelineForText2Image` → serve loop → PNG,
  `via kaggle:sdxl-session`). SDXL registry entry repointed to it (GPU + dataset, slug `pawn-sdxl-session`);
  dropped the unused CPU-POC imports. SDXL session test asserts the GPU push; added a session-slug↔title
  invariant test. No frontend change (already MIME-aware). 134 backend tests green; anon-key-only
  injection still verified for sdxl. **Live verify pending:** SDXL → Start warm session → `Warm` in
  ~1–2 min → Generate returns an image in seconds.

---

- [x] **W.4 — Session startup observability**
  Notebooks patch `installing` → `loading_model` → `ready` at phase boundaries.
  `_LIVE_STATUSES` extended. `SessionBar` shows phase-specific messages ("Waiting for GPU…" / "Installing…" / "Loading model…"). No schema changes.

- [x] **W.5 — Independent per-model panels**
  Tab switcher removed from `ImageLabPage`. All models rendered simultaneously as stacked `ModelPanel` components — each owns its own jobs poll, `SessionBar`, `ImageGenerator`, and `GenerationsPanel`. No cross-model job mixing.

- [x] **W.6 — Session liveness + cold-vs-warm routing fixes**
  `IMAGE_SESSION_HEARTBEAT_STALE_SECONDS`: 30 → 90. `create_cold_job` blocks when warm session is live. Kaggle GPU limit error surfaced as actionable message. `SessionBar` confirm dialog before re-Start.

---

## Phase 6 — UI Routing + Global Polish (imageLab branch)
*Plan reference: `workspace/implemented_phases/phase_6_ui.md`*

- [x] **Phase 6 UI — URL-based routing refactor**
  `react-router-dom` installed. `AppContext.tsx` lifts cross-route state (theme, models, prefs).
  `Layout.tsx` owns Sidebar + Outlet + global dark mode toggle (visible on all routes).
  `ChatPage.tsx` extracts chat logic; URL ↔ store sync via `useParams` + `useEffect`.
  `SettingsPageWrapper` / `ImageLabPageWrapper` thin pages replace direct component rendering.
  `App.tsx` down to 44 lines. `Sidebar.tsx` uses `useNavigate`/`useLocation` internally.
  tsc zero errors; `npm run build` clean.

- [x] **Settings page layout redesign**
  Restructured settings page to 3 responsive vertical columns for desktop viewports. Refined responsiveness of BYOK API key inputs and vertical Kaggle input fields; grouped bubble color presets into horizontally scrollable carousels with aligned horizontal start offsets and chevron scroll buttons.
- [x] **Settings page layout polish & API keys row alignment**
  Reverted global theme toggle to a single animated micro-interaction button. Refactored Settings Page columns (Appearance & Defaults) to stack controls, preventing boundary overflow on narrow column sizes. Corrected sliding theme selector background alignment calculation in ThemeToggle.tsx to handle gaps. Made detailed theme switcher responsive (hiding labels and adjusting padding on medium columns/viewports). Refactored Profile card rows (Display Name, Email, Actions) to stack vertically to avoid overflow. Restructured ApiKeysSection.tsx cards into separate rows for Title, Description, Status (Configured badge and Remove button placed at opposite corners with flex-wrap justification), and Inputs, converting credentials guide descriptions to interactive helper icons that toggle info boxes when clicked/tapped. Reduced outer spacing and card paddings (p-4 to p-3, gap-6 to gap-4, px-6 to px-4) across the Settings page. tsc zero errors; npm run build clean.

---

## Phase D — Production Deployment (Self-Hosted Postgres Migration + Oracle VPS)
*Plan reference: `workspace/plan/plan_deployment.md`*
*Branch: dev (merges → main)*

Drop Supabase for a self-hosted Postgres+pgvector database, fix the three
hardcoded-localhost prod blockers, and write a full `deployment.md` runbook
for PAWN as a second, isolated app on the existing Oracle Cloud Always-Free
ARM VM that already hosts Enma (same account — see plan for the reversed
decision and coexistence rules).

- [x] **D.1 — Kill hardcoded localhost values (CORS, OAuth redirect, CSP)**
  `backend/app/config.py` gains `CORS_ORIGINS`/`FRONTEND_URL`/`OAUTH_REDIRECT_URI`/
  `CSP_CONNECT_SRC` env-var-backed constants (defaults = today's localhost values).
  `main.py` CORS built from `CORS_ORIGINS` (comma-split, wildcard `*` guarded
  against — raises at startup). `routes/auth.py` `_FRONTEND_URL`/`_REDIRECT_URI`
  now read from config. `middleware/security.py` CSP `connect-src` reads
  `CSP_CONNECT_SRC`. New `backend/tests/test_deployment_config.py` (6 tests:
  defaults, env override, CORS allow/reject, wildcard guard). 148 backend tests
  green. code-reviewer PASS (2 WARN fixed: test-pollution in reload teardown,
  CSP format comment). security-auditor PASS (1 WARN fixed: `*` wildcard guard
  added to CORS_ORIGINS parsing).
- [x] **D.2 — Fix frontend build-time API URL**
  `frontend/.env.example` port fixed 8000 → 8001 (matches actual dev backend
  port). New committed `frontend/.env.production` with
  `VITE_API_URL=https://pawnai.duckdns.org` — confirmed embedded correctly in
  the production build bundle. `npm run build` clean. code-reviewer PASS (1
  NOTE, pre-existing/out of scope). No security audit needed (no
  secrets/auth/uploads touched).
- [x] **D.3+D.4 — Migrate Supabase → self-hosted Postgres+pgvector, and Kaggle
  rendezvous → self-hosted PostgREST** (done together — dropping the Supabase
  secrets in D.3 breaks D.4's Kaggle-payload code otherwise, so both were
  implemented and committed as one change)
  New `backend/app/db/postgres_client.py` (psycopg3 sync client — deliberately
  chosen over asyncpg to avoid a ~20-file async ripple across every
  `run_in_threadpool` call site; `fetchone`/`fetchall`/`execute` helpers plus a
  `transaction()` context manager for atomic read-then-write sequences).
  Rewrote all Supabase `.table()/.rpc()` calls to parameterized SQL in
  `routes/auth.py`, `core/key_store.py`, `core/drive_factory.py`,
  `memory/index.py`, `memory/retrieve.py` (SQL-function calls need explicit
  `::vector`/`::int` casts — found via live-Postgres testing), and
  `core/image_session.py` (full rewrite: session/job CRUD to SQL, `str()`
  wrapping at API boundaries for psycopg's native `uuid.UUID` returns, a
  `_parse_ts` fix for native `datetime` returns, `Json(...)` wrapping for
  jsonb columns; `start_session`/`extend_session`/`submit_session_job` now use
  `transaction()` to close read-then-write race windows). `config.py`:
  `SUPABASE_URL/SERVICE_KEY/ANON_KEY` → `POSTGRES_DSN` (secret) +
  `POSTGREST_PUBLIC_URL` (non-secret, D.4). `postgres/schema.sql` (directory
  renamed from `supabase/` — no longer accurate once Supabase was dropped):
  added
  `pgcrypto` extension (was missing, breaks `gen_random_uuid()`), folded in
  `image_jobs.params jsonb` (previously only in a separate manual-apply file
  that never got auto-mounted — a CRITICAL bug caught by code review before
  merge), added a `pawn_anon` role (NOLOGIN, idempotent `DO` block) with
  `GRANT select/insert/update` on `image_sessions`/`image_jobs` only, RLS
  policies retargeted from Supabase's `anon` to `pawn_anon` (same
  single-user-trial permissive posture as before — scoped JWT still
  deferred, unchanged decision from Phase W). New
  `postgres/init_pawn_anon.sh` sets `pawn_anon`'s password from the
  `postgrest_anon_password` secret via injection-safe `psql -v`/`:'var'`
  substitution (a `.sql` file can't read a secret file). `docker-compose.yml`:
  new `postgres` (pgvector image, healthcheck, named volume
  `pawn_postgres_data`, host port 5433 not 5432 — avoids colliding with a
  sibling project's Postgres) and `postgrest` (internal only, no host port)
  services. `requirements.txt`: dropped `supabase`, added `psycopg[binary]` +
  `pgvector`. Secrets: dropped 3 supabase secrets, added `postgres_password`/
  `postgres_dsn`/`postgrest_anon_password`/`postgrest_db_uri` (`.example`
  files + real generated local-dev values). All 3 Kaggle session notebooks
  (`session_poc`, `image_flux_session`, `image_sdxl_session`) updated: payload
  now carries `postgrest_url` instead of `supabase_url`/`anon_key`; headers
  drop `apikey`/`Authorization` (anonymous PostgREST requests get `pawn_anon`
  automatically via `PGRST_DB_ANON_ROLE`). Also fixed an unrelated pre-existing
  bug: `frontend/.dockerignore` was missing, so the frontend Docker build
  context pulled in local `node_modules` (a broken symlink there crashed
  BuildKit) — added it.
  148 backend tests green (rewrote `conftest.py`, `test_rag.py`,
  `test_image_session.py`, `test_image_jobs.py`, `test_keys_kaggle.py` to mock
  the new SQL functions instead of a chained Supabase-client fake).
  `npm run build` clean (unaffected, backend-only migration).
  code-reviewer FAIL→PASS (1 CRITICAL fixed: missing `image_jobs.params`
  column; 2 WARN fixed: read-then-write races now wrapped in `transaction()`,
  stale "Supabase" wording in docstrings/comments cleaned up).
  security-auditor PASS (fixed 2 WARN: stale unreferenced local Supabase
  secret files deleted, raw OAuth exception no longer leaked to the client in
  `auth.py`'s `/callback`).
  **Live-verified** (not just mocks): brought up real `postgres`+`postgrest`+
  `backend`+`frontend` containers from an empty volume — schema/role init
  scripts ran cleanly, PostgREST connected and served both anonymous reads
  *and* writes to `image_sessions` as `pawn_anon` (correctly denied DELETE,
  matching its grants), backend `/health` and frontend both responded. This is
  ahead of D.6's dry-run requirement, not a replacement for it — D.6 still
  needs a full BYOK + memory-retrieval + Kaggle-job pass.
- [x] **D.5 — Clean-`main` mechanism** (`scripts/promote-to-main.sh`; abandoned
  `.gitattributes merge=ours` after sandbox test proved it broken for
  modify/delete — see plan_deployment.md D.5). Proven against a repo clone;
  first real run deferred to D.8. `dev`→`main` must always use the script.
- [x] **D.6 — Pre-deploy test gate** — pytest 152 green, `npm run build` clean,
  all 3 compose configs valid, and **live-verified the Drive-less 412 path** on
  the running backend (`/conversations` + `/crypto/salt` with a no-Drive JWT →
  412 `not_configured`, not 500). Only the Drive-LINKED happy path remains
  (needs a real Google token) — covered by the D.8 staging verify (§8).
- [x] **D.6b — DROPPED (2026-07-04, no VM staging environment).** Decision
  reversed: `dev` stays local-only (never deployed to the VM); only `main`
  goes to prod (`pawnai.duckdns.org`). D.6's local pre-deploy gate substitutes
  for a dedicated staging box — acceptable given PAWN currently has no public
  user base (Google OAuth consent screen is Testing-mode, allowlist only).
  Local dev and prod now **share the same Google OAuth client** (both
  `localhost` and `pawnai.duckdns.org` redirect URIs registered) and the same
  Google account(s) for login; database/secrets stay **separate** per
  environment (own local Postgres for dev, own Postgres+secrets on the VM for
  prod) so a bad local test can't touch real prod data. See
  `plan_deployment.md` decision 8 for full rationale/tradeoffs (accepted:
  local dev is x86, the VM is ARM64, so ARM-specific issues surface at the
  real prod deploy, not a disposable staging box).
- [x] **D.7 — `deployment.md` + prod compose** — root `deployment.md`
  (originally a two-env staging-first runbook; **now simplified to prod-only**
  per the D.6b decision above — `deployment.md`'s own text still has the old
  staging section and needs a follow-up strip pass before D.8 is run),
  `docker-compose.prod.yml` (parameterized, `config`-validated AND
  live-boot-tested locally: fresh-volume schema init, backend `/health`,
  PostgREST anon rendezvous 200 / denied-table 401), `.env.prod.example`/
  `.env.staging.example` (staging example now unused, harmless to keep),
  `.gitignore` for the real env files. Real-VM run behind Nginx/TLS/OAuth
  still pending D.8.
- [ ] **D.8 — First live deploy (prod only, no staging) + full verify checklist**
  (GATED). Order: strip staging section from `deployment.md` → promote
  `dev`→`main` via `scripts/promote-to-main.sh` → deploy `main` to
  `/opt/pawn` on the VM → full verify (health, HTTPS/CSP, Google OAuth +
  Drive-linked happy path — the one thing D.6 couldn't test locally, BYOK LLM
  round-trip, one Kaggle image-gen job) → confirm Enma untouched.

---

## Plan: Drive-Mandatory Storage (Remove Local-Storage Fallback)
*Plan reference: `workspace/plan/plan_drive_mandatory.md`*
*Branch: dev (merges → main). Reference/last-stable commit: `9350664`
(marked in `workspace/stable_commits.md`).*

Triggered by a passphrase-gate 500 caused by a Drive-scope gap in
`routes/crypto.py`'s error handling. Rather than patch just that route, the
local-filesystem fallback pattern is being removed everywhere — Google Drive
becomes the only storage backend for conversations, uploads, memory-summary
indexing, and the encryption salt. Sequenced before D.5-D.8; folds D.5/D.6 in
as Phase 3.

- [x] **Phase 1 — Backend: remove local-storage fallback, Drive mandatory**
  `core/drive_factory.py` gains `require_drive_for_user()` (raises
  `NotConfiguredError`, HTTP 412, when Drive isn't linked) and `call_drive()`
  (translates ANY Drive-operation failure — API error, insufficient OAuth
  scope, revoked grant — into the same clear error, not a raw 500). Every
  `if drive: ... else: local_storage...` branch removed from `routes/crypto.py`,
  `routes/conversations.py`, `routes/upload.py`, `routes/chat.py`,
  `memory/summarize.py`. Background tasks (`auto_title_background_task`,
  `summarize_conversation_task`) fail soft (log + return) rather than raising,
  since there's no HTTP response to attach the error to. `chat.py` only
  requires Drive when a request actually needs storage (`conversation_id` or
  `doc_id` present) — pure stateless chat still works without Drive linked.
  Deleted now-dead `backend/app/storage/conversations.py` and
  `backend/app/storage/documents.py`.
- [x] **Phase 2 — Tests: mock Drive as available everywhere it's implicitly relied on**
  New `backend/tests/fake_drive.py` (in-memory `FakeDriveStorage` running the
  real `conversations_drive.py`/`documents_drive.py` logic). Rewrote
  `test_conversations.py`, `test_upload.py`, `test_summarize.py`,
  `test_rag.py`, `test_crypto.py`; added 412-error-path tests.
  **Manually verified live** (full docker compose stack) per user request —
  automated pytest run was skipped this pass; re-run before D.6.
  **Related fixes found during manual testing:** removed the unwired Phase 3
  passphrase gate from the auth flow (`App.tsx`, deleted
  `PassphraseGate.tsx`) — it blocked the whole app for a feature that never
  got its encrypt/decrypt-on-write wiring done, pure friction with no
  benefit. Renamed `supabase/` → `postgres/` (schema.sql + init_pawn_anon.sh)
  — stale, misleading name once Supabase was dropped in D.3/D.4; updated
  `docker-compose.yml`'s mounts and all doc references; verified a fresh
  Postgres volume still bootstraps correctly from the renamed files.
- [x] **Phase 3 — Fold in D.5 + D.6** — D.5 done (`scripts/promote-to-main.sh`,
  replacing the abandoned `merge=ours`); D.6 gate done (pytest 152 + build clean
  + compose configs valid + live Drive-less 412 verified). Drive-linked happy
  path deferred to D.8 staging verify.
- [x] **Phase 4 — Review, docs, commit** — code-reviewer + security-auditor ran
  on the full combined Phase 1-3 diff (this had never actually happened for
  Phase 1+2 despite the plan calling for it — closed that gap). Both PASS, 0
  critical. 4 WARN-level findings fixed: stale "Drive is optional/local
  fallback" comment in `routes/auth.py` corrected to match the actual
  Drive-mandatory architecture; `drive_factory.py`'s `_build_drive_for_user`
  and `/auth/drive/status` were silently swallowing exceptions with no
  logging (inconsistent with every other fail-soft path in this same plan) —
  added stderr logging to both; `routes/upload.py` and `routes/chat.py`'s SSE
  catch-all were returning raw exception text to the client — genericized to
  fixed messages with server-side stderr logging instead. 152 backend tests
  still green after the fixes. `plan_deployment.md` D.1-D.7 checkboxes synced
  to `[x]` (previously out of sync with this file). D.5/D.6/D.7 build-validator
  checks (deleted storage files, no leftover local-storage branches, compose
  config valid) independently re-verified. This also folded in the
  D.6b/no-staging simplification decision (see above) and its OAuth/DB
  sharing model between local dev and prod.
- [x] **Follow-up — "Connect Google Drive" control in Settings** — backend
  `GET /auth/drive/status` (real Drive-call check, not token-existence) +
  `ApiKeysSection` Drive row (first in the card, Connected/Not-connected badge,
  Connect/Reconnect → existing `login()` OAuth). Closes the UX loop the
  Drive-mandatory 412 message pointed at. 157 backend tests, build clean.

---

## Working Agreement

- Auto mode: implement steps sequentially, update tracker after every step.
- Tests must pass before marking `[x]`. No exceptions.
- Update this file and `workspace/current_state.md` after every step.
- If blocked (user action needed), document in plan file and move to next implementable step.
