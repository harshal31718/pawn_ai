# PAWN — Build Tracker

Source of truth for *what to build* is the relevant phase plan file in `workspace/plan/` or `workspace/implemented_phases/`.
This file tracks *where we are*. Update it after every step — mark `[x]` only when
tests pass and the step's demo works.

The Claude Code instance inside `/PAWN` uses this file to know what to build next.
Agents should read this before starting any work.

Legend: `[ ]` not started · `[~]` in progress · `[x]` done & verified

---

## Current Status

**Active phase:** Phase MU — Multi-User / Auth / BYOK / Drive
**Active step:** DD-1 — Drive storage layer
**Last completed:** Merge Phase 1.6 → main
**Branch:** dev

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

- [ ] **MA-3** — Auth middleware + route scoping
  `backend/app/middleware/auth.py`, all routes get `user_id` from `request.state`

- [x] **MA-4** — Frontend auth UI + 429 back-off timer ✓
  `frontend/src/contexts/AuthContext.tsx` (AuthProvider, useAuth, OAuth callback handler),
  `frontend/src/pages/LoginPage.tsx` (Google sign-in button with inline SVG logo),
  `frontend/src/api/client.ts` (authHeaders() on all requests, onRateLimit callback, 401 auto-reload),
  `frontend/src/App.tsx` (AuthProvider wrapper, AuthGate, 429 countdown banner, useAuth for displayName),
  `backend/app/events.py` (rate_limit_event + code field on error_event).
  Build passes (tsc + vite). 47 backend tests passing.
  `AuthContext.tsx`, `LoginPage.tsx`, JWT header injection in `client.ts`, rate-limit countdown UI

- [ ] **DD-1** — Drive storage layer
  `backend/app/storage/drive.py` (DriveStorage), `backend/app/core/drive_factory.py`

- [ ] **DD-2** — Conversations → Google Drive
  `backend/app/storage/conversations_drive.py`, updated routes

- [ ] **DD-3** — Uploads → Google Drive
  `backend/app/storage/documents_drive.py`, updated routes

- [ ] **SM-1** — Memory → Supabase pgvector
  Replace `memory/index.py` SQLite with Supabase inserts, replace `memory/retrieve.py` with pgvector search

- [ ] **BK-1** — BYOK key store + /keys routes
  `backend/app/core/key_store.py`, `backend/app/routes/keys.py`

- [ ] **BK-2** — Resolver + normalize per-user key lookup
  `resolver.py` and `normalize.py` accept `user_id` + `db`; fall back to shared secrets

- [ ] **BK-3** — Frontend settings panel
  `SettingsPanel.tsx` (API keys tab + profile tab), settings gear in Sidebar

---

## Working Agreement

- Auto mode: implement steps sequentially, update tracker after every step.
- Tests must pass before marking `[x]`. No exceptions.
- Update this file and `workspace/current_state.md` after every step.
- If blocked (user action needed), document in plan file and move to next implementable step.
