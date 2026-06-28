# PAWN — Current State

Last updated: 2026-06-28
Active step: PERF-2 done — optimistic client cache + fail-proof sync (instant conversation UX over Drive) ✓ — manual verify → commit → merge dev→main
Phase: Phase MU — Multi-User / Auth / BYOK / Drive (all code steps complete; perf hardening for Drive latency)

---

## What's Built

- Step 1: repo directory structure — `backend/app/`, `backend/tests/`, `frontend/src/`, `.gitignore`, `.dockerignore`, `secrets/.gitkeep`
- Step 2: `.claude/` config — CLAUDE.md, AGENTS.md, rules (4), agents (5), skills/build-step, settings.json with hooks
- Step 2.5: Docker scaffolding — `docker-compose.yml`, `constants.py`, `config.py`, secrets-as-files pattern, `backend/Dockerfile`, `backend/requirements.txt`, `frontend/Dockerfile`, 5 `secrets/*.example` files
- Step 3: Static chat UI — React + Vite 8 + TypeScript + Tailwind v4; `ChatWindow`, `MessageInput`, `Message` components; `types.ts`; messages echo locally; `npm run build` passes clean
- Step 4: FastAPI backend — `main.py` with full middleware stack (GZip, Timeout, SecurityHeaders, CORS), `exceptions.py` (ProviderError, NoEndpointError + handlers), `middleware/security.py`, `middleware/timeout.py`; `GET /health` → `{"status":"ok"}`; 2 tests passing
- Step 5: Frontend ↔ backend connected — `src/api/client.ts` with `healthCheck()` (VITE_API_URL, res.ok check), `App.tsx` calls it on mount with `.then(console.log).catch(console.error)`; `.env` gitignored; `npm run build` passes
- Step 6: First real AI response — Gemini 2.5 streaming and `llm_core.py` integration.
- Step 7: Typed SSE events — `backend/app/events.py` (7 builder functions: token, done, error, provider_switch, step, memory_hit, model_call); `routes/chat.py` uses events module, emits typed JSON, adds `X-Accel-Buffering: no` header; `frontend/src/api/client.ts` refactored to `StreamChatCallbacks` object with `switch(type)` dispatch; 6 tests passing
- Step 8: Conversation history — Backend forwards full chat history array to upstream models; verified with history routing tests.
- Step 9: Multi-provider support — `backend/app/core/normalize.py` handles model/provider normalization. Added support for Groq and Cerebras.
- Step 10: Model switcher UI — Grouped provider/model switcher component integrated in React frontend.
- Step 11: Document upload — `backend/app/routes/upload.py` accepts PDF/TXT files, extracts text via `pdfplumber`, and stores it in-memory to inject as system message context in `/chat`. Added attachment UI in the input field.
- Step 12: Multi-chat persistence — Built disk-based conversation serialization (`meta.json` + append-only `messages.jsonl`), REST backend CRUD endpoints, auto-titling background tasks, and a dual-pane layout in React featuring inline renaming and thread deletion.
- Step 13: Complete typed SSE events — Wired `onStep`, `onMemoryHit`, `onModelCall`, and `onProviderSwitch` callbacks in `App.tsx` and updated `types.ts` message interfaces to store active trace sequences dynamically.
- Step 14: Per-chat memory summaries — Built context memory window truncation (saving last 10 messages only in active upstream calls), system prompt prepending of rolling context summaries, and enqueued `summarize_conversation_task` on threshold triggers.
- Step 15: RAG over memory — Integrated hybrid vector-keyword retrieval with `sqlite-vec` (sqlite database with virtual `vec0` + standard metadata table + `FTS5` table + triggers). Linked embeddings to Gemini's `text-embedding-004` (Ollama fallback). Wired retrieval and SSE memory_hit event streams into `/chat`.
- Step 16: LangGraph agent — Replaced single-shot flow with a 5-node StateGraph (load_context, agent, search_memory, ask_model, final). Uses ReAct JSON parser and capability-level purpose routing. Built collapsible frontend TracePanel showing steps, memory hits, and model calls dynamically.
- Step R1: Registry foundation — Created Pydantic ModelEntry and EndpointEntry schemas, database files models.json and endpoints.json seeding, loaded them via loaders module and returned catalogue dynamically on GET /registry/models. Added HuggingFace, GitHub Models, and OpenRouter secret keys.
- Step R2: Rate limiter — Implemented in-memory EndpointRateLimiter tracking rolling RPM/TPM usage, 90% soft-wall blocks, cooldown durations, and dead-host detection.
- Step R3: Resolver + normalize contract change — Implemented Resolver picking optimal active endpoints, simplified normalize.chat_stream signature to accept canonical model_id, routed Agent graph nodes using capability routing, and added provider mapping fallbacks for backward compatibility.
- Step R4: Frontend wiring — Integrated dynamic models dropdown from GET /registry/models, custom animated failover notices inline in chat, and provider badge indicators under assistant message bubbles.
- Hotfix: Port/CORS configuration — `docker-compose.yml` pinned backend to `8001:8000` and frontend to `5174:5173` (range bindings caused backend to land on port 8001 while `VITE_API_URL` still pointed to 8000, a different host service). `VITE_API_URL` updated to `http://localhost:8001`. CORS `allow_origins` extended to include `http://localhost:5174`. `frontend/.env` created for local dev.
- Step R5: UI visual overhaul + LAN access — CSS variable theme system (`@theme`/`:root`/`.dark`) with FOUC-prevention blocking script in `index.html`; `InteractiveGridBackground` animated canvas (184 lines); floating pill header islands with dark mode toggle; top gradient overlays trimmed to `h-16 via-theme-bg/25`; floating bottom input; `ChatWindow` smart scroll; `TracePanel.tsx` deleted — trace logic absorbed into `Message.tsx` as unified metadata row (provider left, "Agent Execution N steps" toggle right) with inline step/memory/model_call cards; `react-markdown` for assistant responses; collapsible long user messages; `MessageInput` auto-resize pill→card morph; `Sidebar` mini-sidebar `w-12`, click-to-expand column, fixed-width flicker-free transition, profile avatar, neutral delete colors, no close-on-thread-switch; registry `ModelResponse` extended with `providers` field; LAN IP `10.95.144.153` added to CORS + `VITE_API_URL`.

### Phase MU — Multi-User / Auth / BYOK / Drive (all code steps complete; awaiting manual Supabase/OAuth setup)

- MA-1: Supabase client (`db/supabase_client.py`) + AES-256-GCM crypto (`core/crypto.py`); 6 new secrets in `config.py`, `docker-compose.yml`, `secrets/*.example`; `requirements.txt` adds supabase, cryptography, google-auth-oauthlib, google-api-python-client, PyJWT.
- MA-2: Google OAuth2 — `core/jwt_utils.py` (HS256, 7-day), `routes/auth.py` (login/callback/me/logout). Callback upserts user, stores AES-GCM-encrypted Drive tokens, redirects to frontend with JWT.
- MA-3: `middleware/auth.py` (Bearer JWT → `request.state.user_id`; public `/health` `/auth/*`); storage scoped by user_id; LangGraph thread_id namespaced `{user_id}:{conv_id}`; `tests/conftest.py` bypass_auth fixture.
- MA-4: Frontend auth — `contexts/AuthContext.tsx`, `pages/LoginPage.tsx`, `App.tsx` AuthGate/AuthProvider, `client.ts` Bearer headers + 401 auto-reload; 429 rate-limit countdown banner; `events.rate_limit_event` + error `code` field.
- DD-1/2/3: Google Drive storage — `storage/drive.py` (DriveStorage), `core/drive_factory.py` (exception-safe `get_drive_for_user` → None → local fallback), `storage/conversations_drive.py`, `storage/documents_drive.py`. Routes (`conversations.py`, `upload.py`, `chat.py`) + `summarize.py` use Drive when available, else local filesystem.
- SM-1: Memory → Supabase pgvector — `memory/index.py` add_chunk → Supabase insert; `memory/retrieve.py` pgvector + FTS via RPC (`match_memory_chunks`/`search_memory_chunks`) with RRF fusion; AgentState.user_id threaded through graph + chat; `supabase/schema.sql`; removed `sqlite-vec`.
- BK-1: BYOK — `core/key_store.py` (AES-GCM encrypt, exception-safe reads), `routes/keys.py` (GET/PUT/DELETE; key values never returned).
- BK-2: `resolver.pick(model_id, user_id=None)` prefers user BYOK key over shared secret (keyed endpoints first, falls back to all if none keyed); `normalize.chat_stream(..., user_id=None)`; graph nodes + chat.py thread user_id.
- BK-3: `components/ApiKeysSection.tsx` (per-provider BYOK manage) integrated into `SettingsPage.tsx`; Profile shows real email + Sign out; Sidebar shows real email.
- BK-4: BYOK-only key resolution — `resolver` no longer falls back to shared `secrets/*` provider keys; `pick()` returns only endpoints with the user's BYOK key and raises a clear "configure your key in Settings" error otherwise. Embeddings (`memory/embed.py`) use the user's `google` BYOK key (`user_id` threaded through `retrieve`/`summarize`). Shared provider secret files retained but unused (deletable later).

### Phase MU — Drive-latency perf hardening (2026-06-28)

- PERF-1: Stop blocking the event loop — all synchronous Drive (`googleapiclient`) + Supabase (`supabase-py`) calls moved off the async loop via `run_in_threadpool` / `asyncio.to_thread` across `chat.py`, `conversations.py`, `upload.py`, `memory/summarize.py`, `memory/retrieve.py`. `storage/drive.py` gains a 20 s socket timeout (`AuthorizedHttp` + `httplib2`), a re-entrant lock (the instance is now shared), and a file-ID cache so reads go by ID (`get_media`, strongly consistent) instead of eventually-consistent name queries. `core/drive_factory.py` caches `DriveStorage` per user (TTL + `evict_user`, evicted on Drive re-link). `core/key_store.py` caches decrypted keys + `prefetch()` (warmed once per chat off-loop).
- PERF-2: Instant conversation UX (optimistic UI + client cache + fail-proof sync) — the client is now the source of truth.
  - Client-owned conversation UUIDs (`crypto.randomUUID`); backend `POST /conversations` accepts an `id` (idempotent `_create`), and `/chat` lazy-creates the conversation when missing instead of 404 (so the first message always materializes it).
  - New frontend store layer: `src/store/conversationCache.ts` (localStorage list+messages cache, debounced save, LRU + ~4 MB cap, corruption-safe, `mergeServerMeta` reconciliation), `src/store/syncQueue.ts` (persisted retry queue: create/rename/delete with backoff, 404-as-success, drains on `online`, survives reloads), `src/store/useConversationStore.ts` (single owner of list/messages/active selection), `src/store/ids.ts`.
  - `App.tsx` rewired to the store: new-chat/switch/delete/rename are instant and optimistic; messages are keyed by conversation (a stream writes to its captured conv even after switching away); the post-send full-list refetch is replaced by a local `commitTurn` + one quiet, debounced title-only merge (fixes glitchy/disappearing messages). `Sidebar.tsx` shows pending-sync dots + an offline banner.
- PERF-2a: Draft "New Chat" — clicking New Chat opens a frontend-only draft (welcome page, no sidebar row); nothing is created on Drive/Supabase/local and no sync op is enqueued until the first message is sent (`promoteDraft` + the chat route's lazy-create materialize it). At most one draft → no duplicate/empty chats. See `workspace/decisions/draft_new_chat.md`.

Test/build status: 57 backend tests passing (added chat lazy-create test); frontend `npm run build` passes clean. **Manual browser verification of the optimistic + draft flow under slow Drive still pending.**

---

## What's Working

- [x] Docker stack running (validated compose configuration)
- [x] Backend health check
- [x] Frontend serving
- [x] Gemini streaming
- [x] Cerebras streaming
- [x] Model switcher
- [x] Document upload (Basic RAG context injection)
- [x] Conversation persistence
- [x] Memory RAG
- [x] LangGraph agent
- [x] Rate-limit failover
- [x] Google OAuth2 login + JWT sessions (code complete; needs OAuth credentials)
- [x] Auth middleware + per-user data scoping
- [x] Google Drive storage (code complete; needs Drive-linked login)
- [x] AES-256-GCM encryption (Drive tokens + BYOK keys)
- [x] Memory → Supabase pgvector (code complete; needs Supabase schema run)
- [x] BYOK per-user keys + settings UI
- [x] 429 rate-limit countdown UI
- [x] End-to-end verified live — OAuth login + Drive-backed conversations + BYOK LLM reply (2026-06-27)

---

## Key File Locations

- Backend entry: `backend/app/main.py`
- Provider routing: `backend/app/core/normalize.py`
- LLM core: `backend/app/core/llm_core.py`
- SSE events: `backend/app/events.py`
- Frontend API client: `frontend/src/api/client.ts`
- Model Switcher UI: `frontend/src/components/ModelSwitcher.tsx`
- App layout: `frontend/src/App.tsx`
- Constants (all paths): `backend/app/constants.py`
- Config (secrets): `backend/app/config.py`

---

## Known Issues / Deferred Items

- **Manual setup required before live use** (see build_tracker.md):
  1. Create Supabase free project; run `supabase/schema.sql`; fill `secrets/supabase_url` + `secrets/supabase_service_key`.
  2. Create Google Cloud OAuth2 Web client; redirect URI `http://localhost:8001/auth/callback`; enable Drive API; fill `secrets/google_client_id` + `secrets/google_client_secret`.
  3. `encryption_secret` + `jwt_secret` already generated (MA-1).
- Until Supabase is configured, `get_drive_for_user()` returns None (→ local filesystem storage) and memory retrieve/add gracefully no-op. Tests rely on this fallback.
- Drive `append_messages` rewrites the whole `messages.jsonl` per call (Drive has no partial append) — fine at normal scale, inefficient for very long chats.
- `memory_chunks` ivfflat index uses `lists = 10` — tune up as data grows.
- Client conversation cache is per-browser. Cross-device divergence is reconciled only via `mergeServerMeta` on next load (last-write-wins on title); genuine multi-device editing is not synced live.
- Reasoning `trace[]` is not persisted to the client cache (final message text only) — traces disappear on reload.
- localStorage cache keeps message arrays for the 30 most-recent conversations (LRU, ~4 MB cap); older conversations re-fetch their messages from Drive on next open.

---

## Agents to Update This File

After every completed step, update:
1. "Last updated" date
2. "Active step" to the next step
3. Add new items to "What's Built"
4. Check off items in "What's Working"
5. Add any deferred issues
