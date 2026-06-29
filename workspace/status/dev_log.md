# PAWN — Development Log

One dated entry per step. Each entry is a brief record of what was built,
what decisions were made, and any issues encountered.
This becomes your interview script and project history.

---

## Format

### [YYYY-MM-DD] — Step N: [Step Name]

**Built:** [brief description]
**Decisions:** [any non-obvious choices made]
**Issues:** [anything that took time or was tricky]
**Tests:** [N passing]
**Commit:** [hash]

---

### 2026-06-15 — Step 1: Create the Repo

**Built:** Directory skeleton — `backend/app/` (main.py, config.py, constants.py, routes/, core/), `backend/tests/`, `frontend/src/`. Stub files only; real content in Steps 2.5 and 4.
**Decisions:** Stub files use one-line comments pointing to the step that fills them in; avoids empty files while keeping the tree readable.
**Issues:** None.
**Tests:** N/A (directory structure only).
**Commit:** chore: init repo — directory structure

### 2026-06-15 — Step 2: Claude Code Config (done in scaffolding session)

**Built:** `.claude/CLAUDE.md`, `AGENTS.md`, `settings.json`, 4 rule files, 5 agent files, `skills/build-step/SKILL.md`. PreToolUse + PostToolUse hooks block secrets writes and force-push.
**Decisions:** Used plan/12-claude-setup-guide.md verbatim as the authoritative source for all .claude/ content.
**Issues:** None.
**Tests:** N/A.
**Commit:** chore: project scaffolding — .claude config, workspace/, secrets pattern

### 2026-06-15 — Step 2.5: Docker Scaffolding

**Built:** `docker-compose.yml` with secrets block, `constants.py` (all paths from `DATA_DIR`), `config.py` (`read_secret()` checks `/run/secrets/` first then env var fallback), `backend/Dockerfile`, `backend/requirements.txt`, `frontend/Dockerfile`, 5 `secrets/*.example` files, empty gitignored placeholder secret files.
**Decisions:** Placeholder secret files created locally (gitignored) so `docker compose config` resolves without real keys. Dockerfiles are minimal stubs — full content in Steps 3 and 4.
**Issues:** None.
**Tests:** `docker compose config` validates cleanly; secrets mount at `/run/secrets/*`.
**Commit:** chore: docker scaffolding — compose, secrets-as-files, constants, config loader

### 2026-06-15 — Step 3: Static Chat UI

**Built:** React + Vite 8 + TypeScript + Tailwind v4 frontend. Components: `ChatWindow` (scrollable, auto-scroll to bottom), `MessageInput` (Enter sends, Shift+Enter newline), `Message` (user bubble right/dark, assistant left/light). `src/types.ts` defines `Message` and `ChatState`. Messages echo locally — no API calls yet.
**Decisions:** Used Tailwind v4 CSS-first setup (`@import "tailwindcss"` + `@tailwindcss/vite` plugin) — no config file needed. Upgraded Vite 6→8 to resolve esbuild high-severity vuln (0 vulns after fix). Module counter (`nextId`) is file-scoped to avoid state management overhead at this stage.
**Issues:** esbuild vuln in Vite 6 — fixed by upgrading to Vite 8 + @vitejs/plugin-react 6.
**Tests:** `npm run build` passes clean (tsc + vite build, 0 type errors, 0 vulns).
**Commit:** feat: static chat UI — message list, input, bubbles

### 2026-06-15 — Step 4: FastAPI Backend

**Built:** `main.py` (FastAPI + middleware stack), `middleware/security.py` (SecurityHeadersMiddleware: X-Frame-Options, CSP, X-Content-Type-Options, Referrer-Policy), `middleware/timeout.py` (45s timeout, SSE paths exempt), `exceptions.py` (ProviderError, NoEndpointError + handlers), `tests/test_health.py` (2 tests).
**Decisions:** Used `httpx2` instead of `httpx` to silence Starlette deprecation warning in TestClient. Exception handlers registered in `main.py` even though no provider routes exist yet — establishes the pattern for Step 6+.
**Issues:** `httpx` deprecation warning from Starlette TestClient — fixed by swapping to `httpx2`.
**Tests:** 2 passed (health returns ok, security headers present). Ran inside Docker container.
**Commit:** feat: fastapi backend — health check, middleware stack

### 2026-06-15 — Step 5: Connect Frontend to Backend

**Built:** `frontend/src/api/client.ts` — `healthCheck()` using `VITE_API_URL ?? localhost:8000` with `res.ok` guard. `App.tsx` updated with `useEffect` calling `healthCheck().then(console.log).catch(console.error)` on mount. Added `.env` to `.gitignore`. Fixed `tsconfig.app.json` missing `"types": ["vite/client"]` (caused TS2339 on `import.meta.env`).
**Decisions:** Kept the `localhost:8000` fallback (matches the plan spec) but added a comment to make the intent explicit. Added `res.ok` check and `.catch()` to surface backend errors clearly rather than swallowing them.
**Issues:** `import.meta.env` TypeScript error — fixed by adding `"types": ["vite/client"]` to `tsconfig.app.json`. Two WARNs from code reviewer (missing res.ok, missing .catch) — both fixed before commit.
**Tests:** `npm run build` passes (tsc + vite, 0 errors, 20 modules). Backend: 2/2 passing.
**Commit:** feat: frontend api client + health check wired

### 2026-06-15 — Step 6: First Real AI Response

**Built:** `backend/app/core/llm_core.py` (shared `httpx.AsyncClient`, `_detect_provider`, `_provider_headers`, `_format_upstream_error`, `close_client`, `stream_llm` async generator parsing OAI-compat SSE). `backend/app/routes/chat.py` (typed `ChatMessage` schema with `role: Literal[...]`, `POST /chat` SSE endpoint). `backend/app/main.py` chat router wired + lifespan for async client shutdown. `frontend/src/api/client.ts` `streamChat()` via fetch + ReadableStream. `frontend/src/App.tsx` `isStreaming` state, streaming assistant placeholder, token accumulation.
**Decisions:** Module-level `httpx.AsyncClient` singleton is a planned deviation; Step 9 refactors to `initialize_managers()` DI. Direct `llm_core` import in `chat.py` (bypassing `normalize.py`) is also planned; `normalize.py` arrives in Step 9. Messages schema typed as `ChatMessage(role: Literal, content: str)` to reject malformed upstream payloads. `close_client()` wired into FastAPI lifespan so the async client shuts down cleanly.
**Issues:** Test used `resp.text` on a streaming response — `httpx2` raises `ResponseNotRead`; fixed to `resp.read().decode()` inside the stream context manager. Code reviewer flagged bare `except Exception` leaking `str(exc)` to SSE stream — fixed to catch only `ProviderError` using sanitized `exc.message`.
**Tests:** 4 passed (test_chat_streams_tokens, test_chat_empty_messages, test_health_returns_ok, test_health_has_security_headers).
**Commit:** feat: first real AI response — llm_core, /chat SSE route, streamChat frontend

### 2026-06-17 — Step 7: Typed SSE Events

**Built:** `backend/app/events.py` — 7 typed SSE builder functions (`token_event`, `done_event`, `error_event`, `provider_switch_event`, `step_event`, `memory_hit_event`, `model_call_event`). `routes/chat.py` updated to emit typed JSON events via `events.*`. `frontend/src/api/client.ts` refactored: `streamChat` now accepts a `StreamChatCallbacks` object and dispatches on `event.type`; all 7 event types handled (optional callbacks silent until their steps land).
**Decisions:** `streamChat` changed from positional function args to a callbacks object — cleaner API as more event types arrive in later steps. Added `X-Accel-Buffering: no` and `Cache-Control: no-cache` headers to the SSE response — prevents Nginx/Docker proxy buffering. Used `switch(event.type)` dispatch rather than `if/else` chain for readability.
**Issues:** None.
**Tests:** 6 passed (4 new chat tests: typed token events, no-raw-strings, SSE headers, empty messages; 2 health tests unchanged). Old 2 chat tests replaced by 4 more precise assertions.
**Commit:** feat: typed SSE events — structured wire format, callbacks object

### 2026-06-17 — Step 8: Conversation History

**Built:** Full conversation history forwarding was already implemented in Step 6 (App.tsx builds `[...messages, userMsg]` and sends to backend; backend forwards entire array to LLM). Step 8 adds the explicit verification test `test_chat_forwards_full_history` — asserts all 3 messages in a multi-turn array reach `stream_llm` in order, proving the backend doesn't truncate to just the latest message.
**Decisions:** No code change required — history forwarding was already correct. Step is complete by adding the test that makes the contract explicit and locked.
**Issues:** None.
**Tests:** 7 passed (1 new: `test_chat_forwards_full_history`; 6 from Step 7 unchanged).
**Commit:** test: assert full conversation history forwarded to LLM provider

### 2026-06-17 — Step 9: Multi-Provider (normalize.py)

**Built:** `backend/app/core/normalize.py` implementing a 6-provider layout (Groq, Cerebras, Gemini, HuggingFace, GitHub Models, OpenRouter) and unified model routing. Added `groq_api_key` secrets files and Docker secrets mounting. Refactored `chat.py` and backend tests.
**Decisions:** Groq selected as top priority due to 800+ tok/s speed. Normalizer maps abstract providers to correct baseUrl, default model, and authorization headers.
**Issues:** Mock patching targets in pytest (must patch `app.core.normalize.stream_llm` instead of `app.core.llm_core.stream_llm`).
**Tests:** 12 passed (5 new provider routing tests).
**Commit:** feat: multi-provider model routing with groq support

### 2026-06-17 — Step 10: Model Switcher UI

**Built:** `frontend/src/components/ModelSwitcher.tsx` featuring grouped capability selector (Fast, Balanced, Research). Passed provider state to backend via `streamChat` body payload.
**Decisions:** Switcher disabled during streaming to avoid mid-stream provider changes that can mess up state logic.
**Issues:** None.
**Tests:** 12 passed; frontend builds cleanly with 0 TypeScript issues.
**Commit:** feat: model switcher UI for selecting providers

### 2026-06-17 — Step 11: Document Upload (pdfplumber)

**Built:** Added `pdfplumber` and `python-multipart` to `backend/requirements.txt`. Implemented `backend/app/storage/documents.py` for in-memory text storage and `backend/app/routes/upload.py` to handle document uploads, extracting content from `.txt` and `.pdf` files. Updated `backend/app/routes/chat.py` to accept `doc_id` and inject the document text as a system message. Added paperclip button and file attachment preview chip in the React frontend (`MessageInput.tsx` and `App.tsx`). Added 6 new integration tests in `backend/tests/test_upload.py`.
**Decisions:** Use `pdfplumber` for text extraction to handle complex multi-column layouts accurately. Store document text in-memory globally in a backend module to facilitate seamless context injection for stateless chat queries.
**Issues:** Encountered FastAPI runtime error due to missing `python-multipart` dependency for form parsing; resolved by installing `python-multipart`.
**Tests:** 18 passed (6 new: upload text, upload PDF mock, unsupported types, empty validation, system message injection, 404 handler). Frontend typechecks and builds cleanly.
**Commit:** feat: document upload text extraction and system prompt injection

### 2026-06-17 — Step 12: Multi-Chat Persistence

**Built:** Created `backend/app/storage/conversations.py` to implement full CRUD file management under `data/conversations/<uuid>/` containing `meta.json` and append-only `messages.jsonl` files. Developed endpoints in `backend/app/routes/conversations.py` and wired them in `main.py`. Integrated conversation loading and auto-titling `BackgroundTask` in `chat.py`. Built `frontend/src/components/Sidebar.tsx` displaying the sorted list of threads and allowing thread creation, deletion, and inline double-click renaming. Updated `App.tsx` and `client.ts` to manage and pass the `conversationId`.
**Decisions:** Automatically seed a clean conversation context on page load if none exist. Delay list refresh by 800ms post-response streaming to allow the background auto-title model generation to complete and write metadata before the frontend fetches.
**Issues:** Encountered argument mismatch in frontend `streamChat` during compilation; resolved by adding `conversationId` parameter to the API client signature and payload.
**Tests:** 21 passed (3 new: REST CRUD endpoints, messages saving to disk, auto-titling trigger). Frontend typechecks and builds cleanly.
**Commit:** feat: multi-chat persistence with sidebar navigation and auto-titling

### 2026-06-17 — Step 13: Complete Typed SSE Events

**Built:** Updated `frontend/src/types.ts` to include the `TraceEvent` schema and an optional `trace` field on the `Message` interface. Wired the remaining SSE callbacks (`onStep`, `onMemoryHit`, `onModelCall`, and `onProviderSwitch`) in `App.tsx`'s `streamChat` invocation to append incoming trace events dynamically onto the active message object.
**Decisions:** Maintain trace logs directly inside the Message object scope in frontend state, preparing the state format for the upcoming TracePanel (Step 16) and provider switch inline notifications (Step R4).
**Issues:** None.
**Tests:** 21 passed; frontend typechecks and builds cleanly.
**Commit:** feat: wire up all remaining typed SSE trace callbacks in frontend state

### 2026-06-17 — Step 14: Per-Chat Memory Summaries

**Built:** Created `backend/app/memory/summarize.py` implementing bullet-point summarization (`summarize_history`) using the fastest LLM and a disk-write task (`summarize_conversation_task`). Added `load_summary` and `save_summary` in `conversations.py`. Integrated context memory window truncation (to the last 10 messages) in `routes/chat.py` and enqueued background summarization triggers whenever the conversation turn count hits multiples of 20.
**Decisions:** Truncate context memory to last 10 messages to avoid context window inflation while keeping recent message turns intact. Prepend `summary.md` inside a dedicated system prompt.
**Issues:** Cleaned up duplicated return statements in the chat router route handler.
**Tests:** 25 passed (4 new: direct summarizer test, context window truncation verify, summary prepend, and background threshold task trigger). Frontend typechecks and builds cleanly.
**Commit:** feat: rolling conversation summaries with context memory truncation

### 2026-06-17 — Step 15: RAG over Memory (sqlite-vec)

**Built:** Integrated sqlite-vec extension loading into a sqlite3 database index manager (`backend/app/memory/index.py`), storing text summaries alongside float32 vector embeddings and FTS5 keyword indexing. Created the embedding query interface (`backend/app/memory/embed.py`) mapping to Gemini's `text-embedding-004` (with Ollama `nomic-embed-text` fallback). Created a hybrid retrieval system (`backend/app/memory/retrieve.py`) merging vector nearest-neighbors and FTS matching using Reciprocal Rank Fusion (RRF). Integrated RAG retrieval in the `/chat` route, prepending retrieved context system messages, and yielding `memory_hit` SSE tokens.
**Decisions:** Request a candidate count multiplier of `top_k * 4` during candidate generation before filtering out the active conversation ID, ensuring we retain a sufficient candidate pool.
**Issues:** None.
**Tests:** 29 passed (4 new RAG integration tests verifying vector search similarity, active thread filtering, FTS5 fallback, and SSE memory hit streams). Frontend typechecks and builds cleanly.
**Commit:** `0b7ac54` (feat: hybrid vector FTS RAG over memories with sqlite-vec)

### 2026-06-17 — Step 16: LangGraph Agent

**Built:** Replaced single-shot streaming route with a 5-node StateGraph compiled with `AsyncSqliteSaver` checkpointer. Implemented ReAct JSON action parser, purpose-to-capability routing map, and database context lifecycle manager. Built TracePanel UI collapsible container displaying steps, memory hits, and model calls underneath assistant chat bubbles.
**Decisions:** Expose `initialize_managers` as an async context manager to wrap the `AsyncSqliteSaver` lifespan properly. Use `adispatch_custom_event` inside nodes to route custom events dynamically into the `graph.astream_events` stream.
**Issues:** Resolved `TypeError` on awaiting `dispatch_custom_event` by swapping to its async counterpart `adispatch_custom_event`. Updated existing integration tests asserting message lengths to account for the planning and final generation steps of the agent runner.
**Tests:** 39 passed (10 new agent tests). Frontend typechecks and builds cleanly.
**Commit:** `08473b0` (feat: LangGraph multi-step agent with checkpointer persistence and UI trace panel)

### 2026-06-17 — Step R1: Registry Foundation

**Built:** Created Pydantic ModelEntry and EndpointEntry schemas, database files models.json and endpoints.json seeding, loaded them via loaders module and returned catalogue dynamically on GET /registry/models. Added HuggingFace, GitHub Models, and OpenRouter secret keys.
**Decisions:** Initialized data registry schemas and seeding loader dynamically on startup.
**Issues:** None.
**Tests:** 41 passing.
**Commit:** `6b51bcc` (feat: model registry foundation with json data endpoints (step R1))

### 2026-06-17 — Step R2: Rate Limiter

**Built:** Implemented in-memory EndpointRateLimiter class that tracks rolling RPM/RPD limits, filters out endpoints exceeding a 90% threshold, handles custom cooldowns for live 429s, and triggers dead-host locks after consecutive failures. Registered limiter in app_initializer lifespan managers and stored on app.state.
**Decisions:** Extended EndpointEntry schema limits in schemas.py to default to None for cleaner instantiation in unit tests.
**Issues:** None.
**Tests:** 47 passing (6 new rate limiter tests).
**Commit:** `da568f4` (feat: endpoint rate limiter with 90% soft-wall and cooldowns (step R2))

### 2026-06-17 — Step R3: Resolver + normalize Contract Change

**Built:** Created Resolver class in `resolver.py` picking optimal active endpoints and supporting capability-level routing. Modified `normalize.chat_stream` signature to accept canonical `model_id`. Updated `/chat` request schema and mapped old `provider` payload fields to model_id for backwards compatibility. Added Groq to seeded endpoints and updated test assertions.
**Decisions:** Handled backward-compatible friendly provider name aliases directly inside the Resolver's pick function and chat.py model_id mapping to allow old tests and client implementations to work seamlessly.
**Issues:** Trailing spaces in Authorization Bearer token header caused Newer HTTPX specifications to reject header format; resolved by stripping the header token string.
**Tests:** 47 passing (unit tests adjusted to account for Groq endpoint addition and custom final provider event propagation).
**Commit:** `83d3d16` (feat: resolver and fallback provider aliases with model_id signature (step R3))

### 2026-06-17 — Step R4: Frontend Wiring

**Built:** Updated `ModelSwitcher.tsx` to retrieve models dynamically from `GET /registry/models` and group options by `capability_level` (Fast, Balanced, Research, Other). Added `fetchRegistryModels` in `client.ts`. Updated `types.ts` with `'notice'` role and `viaProvider` attribute in `Message`. Updated `App.tsx` to handle `onProviderSwitch` (appending a notice message and trace log) and `onDone` (passing and storing `viaProvider`). Added a formatted provider badge under assistant message bubbles in `Message.tsx`. Filtered out `'notice'` messages from chat history sent to backend.
**Decisions:** Handled the custom notice messages purely in frontend state to keep backend conversation logs clean and standard. Explicitly typed `groups` in `ModelSwitcher` to avoid compile time issues with pushing 'other' groups.
**Issues:** None.
**Tests:** 47 passing backend tests. Frontend typescript typechecks and builds cleanly with zero errors.
**Commit:** `88738e2` (feat: frontend wiring for dynamic models, inline failover notices, and provider badges (step R4))

### 2026-06-22 — Hotfix: Port and CORS Configuration

**Built:** Fixed a silent misconfiguration that caused all browser API calls to hit a foreign service instead of PAWN's backend. `docker-compose.yml` used port ranges (`8000-8010:8000`, `5173-5180:5173`); Docker allocated 8001 for the backend and 5174 for the frontend, but `VITE_API_URL` was hardcoded to `http://localhost:8000` (another service) and CORS `allow_origins` only listed `http://localhost:5173`. Pinned ports to `8001:8000` and `5174:5173`, updated `VITE_API_URL` to `http://localhost:8001`, added `http://localhost:5174` to CORS allowed origins, and created `frontend/.env` for local dev outside Docker.
**Decisions:** Fixed port ranges to deterministic values rather than trying to free port 8000 — another service on the host owns it and there is no reason to conflict.
**Issues:** PDF upload (and all other API calls) silently failed because requests went to an unrelated service that happened to return 200 on `/health` but 404 on all PAWN routes.
**Tests:** CORS preflight verified via curl: `access-control-allow-origin: http://localhost:5174`. Upload endpoint confirmed working inside container.
**Commit:** stable: small fixes resolved

### 2026-06-27 — Step R5: UI Visual Overhaul + LAN Access

**Built:**

*Theme & layout system:*
- `frontend/src/index.css` — Full CSS variable theme system: `@theme` block, `:root` light tokens (zinc-based), `.dark` override tokens. Scrollbars hidden globally.
- `frontend/index.html` — Blocking inline `<script>` in `<head>` reads `localStorage['pawn-theme']` and `prefers-color-scheme`, applies `.dark` before first paint to eliminate FOUC theme flash.
- `frontend/src/App.tsx` — Responsive `isSidebarOpen` state (open ≥768px); `darkMode` state with localStorage + `prefers-color-scheme`, synced via `useEffect` to `document.documentElement`. Floating pill header islands (left: title + sidebar toggle, right: ModelSwitcher + dark mode toggle). Top-corner gradient overlays set to `h-16 via-theme-bg/25` (reduced from h-28/via-50 to avoid masking scrolled text). Floating bottom gradient input area. Sidebar receives `isOpen/onClose/onOpen` props.

*New component:*
- `frontend/src/components/InteractiveGridBackground.tsx` — 184-line animated canvas dot-grid reacting to mouse position; receives `darkMode` prop.

*Message rendering:*
- `frontend/src/components/Message.tsx` — `react-markdown` for assistant messages with custom component overrides (ul/ol/li, p, h1-3, pre, code inline+block, a). User messages: height >140px triggers collapsible fade overlay + "more/less" button. Unified metadata row below assistant bubble: provider name left, "Agent Execution (N steps)" toggle button right. Trace panel logic inlined (replaces deleted `TracePanel.tsx`): step/memory_hit/model_call rows in a `max-h-60` scrollable card using `bg-theme-bg` to blend with page. Auto-collapses trace 500ms after streaming ends. `w-fit` container with `ml-auto`/`mr-auto` so trace card aligns to bubble edges. `relative z-10` on metadata + trace rows fixes canvas dot bleed-through.
- `frontend/src/components/TracePanel.tsx` — **Deleted** (logic absorbed into Message.tsx).

*Input:*
- `frontend/src/components/MessageInput.tsx` — Auto-resize textarea clamped at 138px. `isMultiLine` state: pill → card morph on expansion.

*Sidebar:*
- `frontend/src/components/Sidebar.tsx` — Mini-sidebar collapsed width narrowed from `w-16` to `w-12`, padding `px-1`. Clicking the blank collapsed column expands (outer wrapper has `onClick={onOpen}`; icon buttons call `e.stopPropagation()`). Inner container uses fixed widths (`w-64` expanded, `w-12` collapsed) so the parent clips as a curtain — eliminates "New Chat" text-squish flicker. Profile avatar badge ("H", `w-8 h-8 bg-theme-brand rounded-full`) rendered below settings icon in collapsed state. Delete icon and confirmation popup colors neutralized to zinc (red removed). Conversation item clicks no longer call `onClose`, keeping sidebar open on thread switches.

*Registry API:*
- `backend/app/registry/schemas.py` — Added `providers: List[str] = []` to `ModelResponse`.
- `backend/app/routes/registry.py` — Populates `providers` as sorted unique set of endpoint provider names per model.
- `frontend/src/api/client.ts` — Added `providers: string[]` to `RegistryModel`.

*LAN access:*
- `backend/app/main.py` — Added `http://10.95.144.153:5174` to CORS `allow_origins`.
- `docker-compose.yml` — `VITE_API_URL` set to `http://10.95.144.153:8001` for cross-device testing.

- `frontend/package.json` — Added `react-markdown` dependency.

**Decisions:** LAN IP `10.95.144.153` hardcoded for testing session — revert to `localhost` before merging to main. `react-markdown` over MDX for simplicity; no syntax highlighter added yet. Smart scroll freezes on alignment (not pinned to bottom) for better UX during long streamed responses. Trace auto-collapse delay (500ms after `isStreaming` → false) gives the user a moment to see the final state before it closes.
**Issues:** None.
**Tests:** 47 passing backend (no new backend tests). Frontend TypeScript build: pending verification before merge.
**Commit:** (uncommitted — working tree changes on dev branch)

---

### 2026-06-27 — Phase MU: Multi-User / Auth / BYOK / Google Drive (all code steps)

**Built:** Transformed PAWN from single-user local app to multi-user system.
- **Auth (MA-1..MA-4):** Google OAuth2 (`routes/auth.py`), JWT sessions (`core/jwt_utils.py`, HS256/7-day), `middleware/auth.py` (Bearer → `request.state.user_id`, public `/health` `/auth/*`), AES-256-GCM crypto (`core/crypto.py`), Supabase client (`db/supabase_client.py`). Frontend: `AuthContext`, `LoginPage`, AuthGate, Bearer headers + 401 auto-reload, 429 countdown banner.
- **Drive (DD-1..DD-3):** `storage/drive.py` (DriveStorage), `core/drive_factory.py` (exception-safe `get_drive_for_user` → None → local fallback), `conversations_drive.py`, `documents_drive.py`. Routes + summarize use Drive when available, else local filesystem.
- **Memory (SM-1):** Replaced sqlite-vec with Supabase pgvector. `memory/index.py` add_chunk → insert; `memory/retrieve.py` → pgvector + FTS via RPCs `match_memory_chunks`/`search_memory_chunks` with RRF fusion in Python. `AgentState.user_id` threaded through graph + chat. `supabase/schema.sql` created.
- **BYOK (BK-1..BK-3):** `core/key_store.py` (AES-GCM, exception-safe), `routes/keys.py` (GET/PUT/DELETE; values never returned). `resolver.pick(model_id, user_id)` prefers user key over shared secret. `normalize.chat_stream(..., user_id)`. Frontend `ApiKeysSection.tsx` in `SettingsPage` + Sign out + real email.

**Decisions:**
- App data (profiles, encrypted tokens, BYOK keys, memory embeddings) → Supabase free tier; user data (conversations, uploads) → user's own Google Drive.
- Backend-proxy BYOK (keys decrypted server-side, never reach frontend) — avoids CORS and key exposure. Edge-proxy is a future optimization.
- Graceful degradation everywhere: Supabase/Drive unavailable → fall back to local filesystem and no-op memory, so tests pass without external services.
- `resolver.pick` keeps legacy behaviour when no key resolves (returns all available) so shared-secret/dev/test path is preserved.

**Issues:**
- All existing tests would 401 after auth middleware → added `conftest.py` bypass_auth fixture.
- Test/storage user_id mismatch after scoping → tests pass `user_id="test-user-id"`.
- `KeyError: 'user_id'` in load_context/search_memory nodes (test states lack it) → use `state.get("user_id")`; updated one call-args assertion.
- Rewrote `test_rag.py` to mock Supabase (no live pgvector in tests).
- Fixed pre-existing frontend unused-var build errors (`useCallback`, `isAuthenticated`).

**Tests:** 56 backend tests passing (47 prior + 7 keys + 2 net new rag mocks/agent). Frontend `npm run build` passes clean.
**Blocked on (manual):** Supabase project + `supabase/schema.sql`; Google OAuth2 credentials. Then verify end-to-end and merge dev → main.
**Commit:** (uncommitted — working tree changes on dev branch)

### 2026-06-27 — BK-4: BYOK-only key resolution (drop shared-secret fallback)

**Built:** Provider API keys now come *exclusively* from the user's Settings-configured BYOK keys (Supabase `key_store`); the shared `secrets/*` provider keys are no longer used for LLM or embedding calls.
- `resolver._resolve_key` — removed the `self._secrets.get(ep.secret)` fallback; returns only the user's BYOK key (or "" when none).
- `resolver.pick` — returns only endpoints that carry a usable BYOK key. When the user has no key for any available provider, raises `NoEndpointError("No API key configured for {provider}. Add your provider key in Settings to use this model.")` instead of silently returning unkeyed endpoints.
- `memory/embed.py` — `embed(text, user_id=None)` resolves the Gemini embedding key from the user's `google` BYOK key (`_resolve_gemini_key`); dropped the `from app.config import GEMINI_API_KEY` import. Ollama fallback unchanged.
- `memory/retrieve.py` / `memory/summarize.py` — thread `user_id` into `embed()`; `summarize_history(..., user_id)` passes it to `chat_stream` so summaries use BYOK too.
- Tests: `conftest.py` adds an autouse `stub_byok_key` fixture (patches `key_store.get_key` → `"TEST-BYOK-KEY"`) so the test user "has" keys; `test_keys.py` `test_resolver_falls_back_to_shared_secret` → `test_resolver_raises_when_no_byok_key`; `test_rag.py` mock_embed signatures accept `*args, **kwargs` for the new `user_id` kwarg.

**Decisions:** Kept the now-unused `secrets` constructor param on `Resolver` (and the shared secret files themselves) for backward compatibility — the dependency is removed in behaviour, files can be deleted later. Embeddings degrade gracefully without a key: `retrieve()` already catches embed failures (FTS-only) and summary indexing runs in a background task.
**Issues:** Compose uses `develop.watch` (sync), not a bind mount — running container kept old code until `docker compose up -d --build backend`. Verified live: BYOK key → endpoints resolved without shared key; no key → clear NoEndpointError.
**Tests:** 56 backend tests passing.
**Commit:** (uncommitted — working tree changes on dev branch)

### 2026-06-28 — Perf fix: stop blocking the event loop on Drive/Supabase I/O

**Symptom:** After enabling login, chats had long load times, intermittent "no replies", and history that randomly disappeared. Worked sometimes, broke under any concurrency.

**Root cause:** The multi-user path (commit 410e4b7) introduced synchronous, blocking I/O — Google Drive (`googleapiclient`) and Supabase (`supabase-py`) — called directly inside `async def` routes and async LangGraph nodes. FastAPI runs on a single event loop; a blocking call there freezes *every* concurrent request. A single chat with a `conversation_id` did ~12 serial Drive round-trips (meta + messages + summary, each re-resolving folders by name) before the LLM even started, plus blocking Supabase calls for BYOK keys (per reasoning step) and memory retrieval. No timeouts meant a stalled Drive call hung the request forever. Drive's eventually-consistent name queries (`find_file` right after a write) returned None → "disappearing history".

**Built:**
- `storage/drive.py` — socket timeout (`AuthorizedHttp(creds, httplib2.Http(timeout=20))`); re-entrant lock guards all API access (the instance is now shared across threadpool workers, and googleapiclient's transport isn't thread-safe); file-ID cache so reads go by ID via `get_media` (strongly consistent) instead of name queries; caches cleared on delete.
- `core/drive_factory.py` — per-user `DriveStorage` cache (TTL 10 min live / 30 s for not-linked) + `evict_user()`; avoids refetching tokens and rebuilding the service every request. `auth.py` evicts on (re)link.
- `core/key_store.py` — short-TTL decrypted-key cache + `prefetch(user_id)` (one query warms all providers); `set_key`/`delete_key` evict.
- Routes (`chat.py`, `conversations.py`, `upload.py`) and `memory/summarize.py` — every blocking Drive/Supabase/`key_store`/PDF-parse call moved off the loop via `run_in_threadpool`; conversation reads batched into a single hop. `chat.py` warms the key cache once per request.
- `memory/retrieve.py` — the two Supabase RPCs wrapped in `asyncio.to_thread`.

**Decisions:** Kept Drive as the conversation store (per user direction) and fixed it in place rather than migrating to local FS/Supabase. Consistency relies on the cached instance's file-ID map surviving across requests; the brief not-linked cache window is self-healing.
**Issues:** Caching `None` from a Supabase blip could mask a linked user's Drive (showing empty local storage); mitigated with a short 30 s TTL on negative results and a 10 min TTL on live instances.
**Tests:** 56 backend tests passing (unchanged).
**Commit:** (uncommitted — working tree changes on dev branch)
**Next (manual verify):** Live test under Docker with a linked Drive — concurrent chats, no event-loop stalls, history persists across reloads.

### 2026-06-28 — PERF-2: Instant conversation UX (optimistic UI + client cache + fail-proof sync)

**Symptom (Drive mode):** New chat slow + created duplicates; switching laggy ("won't open then suddenly loads"); delete slow/unreliable (row lingered, double-clicked); messages glitched/disappeared after send.

**Root cause:** Every conversation action awaited slow Drive round-trips with no client cache, and `onDone` ran a full-list refetch that *reset* `activeConvId`, re-firing the load effect and reloading messages from eventually-consistent Drive — clobbering the just-streamed turn.

**Design (user-approved plan):** Make the client the source of truth. Client-owned UUIDs + localStorage cache drive the UI instantly; Drive persistence drains in a fail-proof background queue; server fetches become reconciliation merges, never authoritative resets.

**Built:**
- Backend (2 small edits): `conversations.py` `ConversationCreate.id` + idempotent `_create` (returns existing meta if the id exists); `chat.py` lazy-creates the conversation when `conversation_id` meta is missing instead of 404 (so the first message materializes it). Both storage backends already accept `conv_id`; no test depended on the 404.
- Frontend store layer (new): `store/ids.ts` (UUID + collision-free message ids), `store/conversationCache.ts` (per-user localStorage cache of list + messages; debounced save; LRU(30) + ~4 MB eviction; corruption-safe load; `mergeServerMeta` merge rules), `store/syncQueue.ts` (persisted create/rename/delete queue with exponential backoff, idempotent ordering, DELETE-404-as-success, drains on `online`, survives reloads), `store/useConversationStore.ts` (single owner of list/messages/active selection + optimistic mutators + bootstrap/reconcile).
- `client.ts`: `createConversation(..., id?)`; `deleteConversation` treats 404 as success.
- `App.tsx`: removed `conversations`/`activeConvId`/`messages` local state, the awaiting switch effect, and the `handleCreate`/`handleDelete`/`handleRename`/`refreshConversations` handlers; wired to the store. Messages are keyed by conversation, so a stream writes to its **captured** conv id even if the user switches away. `onDone` now does `bumpAfterTurn` (local list update) + debounced `quietTitleRefresh` (title-only merge) instead of the disruptive full refetch.
- `Sidebar.tsx`: removed the stale empty-chat dedupe (now race-free in the store); added pending-sync dots + an offline banner.

**Decisions:** Full fail-proof persisted sync queue (not lighter in-memory) and localStorage-persisted messages — both chosen by the user. On switch, trust cache and only background-fetch when a conv has NO cached messages (avoids clobbering just-sent turns under Drive eventual consistency).
**Issues:** Streaming-during-switch required moving message ownership into the store keyed by conv (App's single `messages` buffer would have appended to the wrong conversation). Multi-device + trace persistence are documented limitations.
**Tests:** 57 backend tests passing (added `test_chat_lazy_creates_unknown_conversation`); frontend `npm run build` clean.
**Commit:** (uncommitted — working tree changes on dev branch)
**Next (manual verify):** Browser test under slow Drive — instant new-chat (no dupes) / switch / delete; messages persist + reconcile after reload; kill backend → ops queue in `localStorage['pawn-syncq:*']` and drain on restart/`online`.

### 2026-06-28 — PERF-2a: Draft "New Chat" (no persistence until first message)

**Change:** New Chat no longer creates anything on the backend. It opens a frontend-only *draft* (welcome page, empty in-memory buffer); the conversation is materialized — sidebar row + Drive file — only when the first message is sent.

**Built:**
- `store/useConversationStore.ts`: added `draftConvId` state; `createConversation()` now opens/reuses the single draft (no list insert, no `create` enqueue, no network); new `promoteDraft(id)` adds the meta to the list at first send and clears the draft. Persist effect excludes the draft from the localStorage cache.
- `App.tsx` `handleSend`: calls `promoteDraft(convId)` before streaming (no-op for already-real convs); the chat route's lazy-create writes it to Drive on that request. Sidebar `onCreate` simplified to `createConversation()`.
- `store/syncQueue.ts`: the `create` op is now unused (commented as defensive/kept).
- Behavior contract documented in `workspace/decisions/draft_new_chat.md`.

**Decisions:** Sidebar shows NO row for the draft (user choice) — the titled row appears only after the first message. At most one draft → no duplicate empty chats. An unsent draft does not survive reload (nothing to persist).
**Tests:** No backend change (lazy-create already covered). Frontend `npm run build` clean.
**Commit:** (uncommitted — working tree changes on dev branch)
**Next (manual verify):** New Chat → no network request, no sidebar row, welcome page; spam → one draft; first message → row + one `POST /chat` lazy-create; reload → row+messages persist.

### 2026-06-28 — Per-conversation streaming (concurrent chats)

**Built:** "Is generating" and the rate-limit cooldown were global single values, so sending in one chat blocked sending in every other chat while it streamed. Made both per-conversation. Store: `streamingConvIdRef` (single) → `streamingConvIds: Set<string>` state + ref; `setStreaming(convId, on)` add/removes; `selectConversation` refetch-skip guard uses `.has(id)`. App: removed the global `isStreaming` and the four singleton stream refs (`abortRef`/`streamingIdRef`/`lastUserRef`/`streamConvIdRef`), replaced with one `streamsRef: Map<convId, {assistantId, controller, userMsgId, userContent}>`. Composer/ChatWindow now gate on `isActiveStreaming` (active conv only). Rate limit moved from one `rateLimitCountdown` to `rateLimitUntil: Record<convId, epochMs>` with a single 1s ticker; the active conv's remaining time is derived.
**Decisions:** `handleStop` targets the conversation currently being viewed (each has its own AbortController). Send is blocked only for the conv already streaming, not globally. `isUploading` stays global (active-conv attachment action). Per-conversation drafts remain out of scope — `draft` is still one shared input for the active conv.
**Tests:** No backend change. Frontend `npm run build` clean (tsc + vite).
**Commit:** (uncommitted — working tree changes on dev branch)
**Next (manual verify):** Open chat A, send long prompt; while streaming switch to B and send → both stream; switching back to A still shows live tokens + Stop; Stop restores A's text; rate-limit A → only A's composer shows countdown, B sendable; second send into a streaming chat still blocked.

### 2026-06-28 — Key-aware model selection + cross-model rate-limit failover

**Built:** Fixed two BYOK issues: (1) selecting a Google model still errored "No API key configured for cerebras", and (2) no fallback when a provider was rate-limited.
- **Root cause of cerebras error:** when the user's Gemini endpoint got rate-limited, the agent's `pick_model_by_capability("fast")` (graph.py) fell through to the next available fast model — GLM 4.7 (Cerebras) — because it only checked `active`+`can_use`, never whether the user had a key. `normalize.chat_stream → resolver.pick(user_id)` then rejected it.
- **resolver.py:** `pick_model_by_capability`/`pick_by_capability` now take `user_id` and only consider models with ≥1 endpoint the user holds a key for (new `_has_usable_endpoint`). Added `usable_user_models(user_id)` and `fallback_models(model_id, user_id)` (requested model first, then other usable models, same capability_level first).
- **normalize.py:** extracted `_stream_one_model` (per-endpoint failover, unchanged) and rewrote `chat_stream` to iterate `fallback_models` — on rate-limit/no-endpoint *before the first token*, it switches to another usable model (new `on_model_switch` callback); mid-stream errors still propagate (can't restart a partial reply).
- **graph.py:** agent/ask_model nodes pass `user_id` and fall back to `state["user_model_id"]` on `NoEndpointError`; all three model-calling nodes pass `on_model_switch` (reuses the existing "Failing over" provider_switch notice). `DummyResolver` updated.
- **Frontend:** `App.tsx` fetches the user's configured providers via `getKeys()` and derives `availableModels` (models served by ≥1 keyed provider); the composer picker + Settings default-model list now show only usable models. Selection/default coerce to a usable model when the current pick isn't available. Empty-state hint links to Settings. Key add/remove triggers `onKeysChanged` → re-fetch so the picker updates without reload.

**Decisions:** `/registry/models` stays the global catalogue; per-user filtering is a frontend view concern. Cross-model fallback only triggers before the first token. "grok" = Groq (no separate xAI provider).
**Tests:** Backend 66 passed (added `test_resolver.py`, `test_normalize_fallback.py`). Frontend `npm run build` clean. Backend + frontend images rebuilt and running (8001/5174 healthy).
**Commit:** (uncommitted — working tree changes on dev branch)
**Note:** Earlier `drive.py` client_id/secret fix was baked into the image with this rebuild (the dev `watch` sync wasn't running, so prior `restart` hadn't picked it up).

### 2026-06-28 — Image-gen pipeline working (T4 fix + deploy auto-queue) [imageLab]

**Context:** Milestone A.0 image generation (SDXL on the user's own Kaggle account) had the kernel transport working but two blockers stopped end-to-end generation.

**Built / fixed:**
- **T4 GPU fix** (`core/kaggle.py`): runs always landed on a P100 (Pascal) and failed with CUDA kernel mismatch / `Torch not compiled with CUDA enabled`. Root cause: the `/kernels/push` body sent the GPU type under `accelerator`, which Kaggle silently ignores → default P100. The wire field is `machineShape` (the SDK's `machine_shape` / CLI `--accelerator`; valid values `NvidiaTeslaT4`, `NvidiaTeslaP100`, `Tpu1VmV38`). Changed `body["accelerator"]` → `body["machineShape"]`. `generate_image` already passes `NvidiaTeslaT4`. Verified live: image returned in ~127s.
- **Deploy → "Kaggle is busy" auto-queue** (`core/kaggle.py`, `constants.py`): a Kaggle push always starts a run, so the deploy warmup leaves the slug `queued`/`running` for ~1–2 min; clicking Generate during that window hit the pre-flight busy check and errored instantly. Replaced the immediate raise with `_wait_until_idle(...)` — polls `/kernels/status` until the slug reaches any terminal state (complete *or* failed, so a failed warmup doesn't block), bounded by new `KAGGLE_BUSY_WAIT_TIMEOUT_SECONDS = 300`; only raises "still busy" if it never frees. `run_kernel` gains a `busy_wait_timeout` param. Generate now transparently queues behind the warmup.
- **Frontend** (`ImageLabPage.tsx`): running indicator now notes it "waits for warmup if just deployed"; Generate stays enabled (backend queues).

**Decisions:** Backend auto-queue chosen over a frontend cooldown/readiness-poll — no time guessing, no new endpoint, robust to variable warmup duration (user-approved plan).
**Issues:** Public Kaggle API has no documented value for dual T4 (T4×2) — issue #821 unanswered; we use a single T4. Image quality not yet tuned (out of scope for now).
**Tests:** 13 `test_generate.py` tests passing (3 new `_wait_until_idle` tests: waits-through-inflight, times-out, proceeds-on-non-200). Frontend `npm run build` clean.
**Commit:** (this commit)

### 2026-06-29 — W.0: persistent Kaggle loop proof (CPU echo) + Supabase rendezvous [imageLab]

**Context:** Phase W Step W.0 — the load-bearing risk for warm sessions is *"can a batch-pushed Kaggle kernel run a long-lived internet loop for tens of minutes?"* De-risked it with the cheapest payload (CPU echo, no GPU/model), exactly as the cube POC de-risked the transport.

**Built:**
- **Schema** (`supabase/schema.sql`): `image_sessions` + `image_jobs` tables (+ indexes). RLS intentionally left disabled for the single-user W.0 trial (anon key has full access — the documented fallback); scoped per-session JWT + RLS policies are the W.1 deliverable.
- **CPU echo notebook** (`kaggle_templates/session_poc/notebook.ipynb`): decodes the injected payload, PATCHes `status='ready'`, then loops on Supabase REST (`requests`): heartbeat each iteration, echo any pending job's prompt into `image_b64`, honor stop/timer/cap, exit cleanly.
- **Session manager** (`core/image_session.py`): `start_session` (evict prior live → insert row → inject anon key + url payload → non-blocking `kaggle.deploy_kernel` push, CPU/internet, no dataset), `get_session_status` (liveness = status + fresh heartbeat + before expiry), `stop_session` (cooperative flag), `submit_session_job` (alive-guard → queued row), `get_job`. All Supabase/Kaggle calls blocking → routes off-load via `run_in_threadpool`.
- **Routes** (`routes/generate.py`): `POST /generate/session/start|job|stop`, `GET /generate/session/status`, `GET /generate/job/{id}`. Session start reuses the per-`(user,model)` lock.
- **Config/secrets**: new `supabase_anon_key` (PUBLIC) via `read_secret` + docker-compose `secrets:` block + committed `.example`; real file gitignored. Service key is NEVER injected into the notebook.
- **Constants**: poll interval (3s), heartbeat-stale (30s), max-duration backstop (120 min), POC slug/template path.
- **Frontend**: `client.ts` helpers (start/status/job/stop/getJob, typed `SessionStatus`/`JobResult`); minimal `components/SessionPocPanel.tsx` (duration/cap picker, live countdown, submit echo job + poll, Stop) wired into `ImageLabPage` under the active model when connected.

**Security:** Audited (security-auditor PASS, 0 critical) — only the public anon key + url reach the notebook (dedicated test base64-decodes the payload and asserts the service key is absent); payload base64-injected (no code injection from prompt); no key logging. Code-reviewer PASS, 0 critical. WARN fixes applied: `start_session` fails early (412) if Supabase url/anon key missing; `submit_session_job` rejects jobs to a non-live session; conftest seeds `SUPABASE_ANON_KEY`. Deferred to W.1 (documented WARNs): RLS policies + scoped JWT (session_token is inert until then).

**Tests:** 117 backend passed (24 new in `test_image_session.py`: manager + all 5 routes, mocked Supabase/Kaggle). Frontend `npm run build` clean.
**Live verify (manual, pending user setup):** run the new schema in Supabase + add `secrets/supabase_anon_key`, then Image Lab → connect → Start warm session → submit echo job → watch the CPU kernel pick it up, echo back, heartbeat, and exit on Stop/expiry.
**Commit:** (this commit)

### 2026-06-29 — W.0 LIVE-VERIFIED + new-key RLS gotcha [imageLab]

**Live result:** Image Lab → Start warm session → kernel reached **Warm** with a live countdown (29:12) and fresh heartbeat; 2 echo jobs round-tripped through Supabase (queue → kernel pickup → result write → UI read-back: "ECHO: really"). The load-bearing assumption — a batch-pushed Kaggle kernel can run a long-lived internet loop + Supabase rendezvous — is **PROVEN**.
**Gotcha caught by the probe (before any Kaggle run):** Supabase's new `sb_publishable_*` key enforces RLS on the anon role, so "RLS off for the trial" didn't hold — the kernel could READ but INSERT/PATCH 401'd (`42501`). Fix: enable RLS + a permissive anon policy on `image_sessions`/`image_jobs` (commit `043a7f3`) — the documented "anon-key-open on the two dedicated tables" trial fallback. Re-probe confirmed READ/INSERT/PATCH/DELETE all succeed with the publishable key. W.1 narrows this to a scoped per-session_id policy.
**Commit:** 043a7f3 (RLS fix) + tracker/state updates.

### 2026-06-29 — W.1: warm FLUX serve-loop + unified durable job layer [imageLab]

**Built:**
- **FLUX persistent notebook** (`kaggle_templates/image_flux_session/notebook.ipynb`): cell-0 payload + Supabase REST helpers (anon key bearer; `session_jwt` honored if present — W.1 follow-up); cell-1 pip install; cell-2 load FluxPipeline ONCE (bf16, balanced device_map across 2× T4, VAE tiling, CPU-offload fallback) → PATCH `ready`+heartbeat (or `error`+exit); cell-3 serve loop (heartbeat, honor stop/timer/cap, 4-step/guidance-0/1024² inference → PATCH job `done`+PNG b64).
- **Registry-driven sessions** (`core/image_models.py`): `ImageModel` gains `session_template`/`session_slug`/`session_gpu`. FLUX → real GPU serve-loop (`pawn-flux-session`); SDXL → CPU echo POC (cheap loop/monitor testing without GPU). `start_session` reads these (GPU+dataset for FLUX, CPU/no-dataset for echo).
- **Session manager** (`core/image_session.py`): `extend_session` (bump `expires_at`, capped at the 120-min backstop, rejects a non-live session).
- **Unified durable job layer (the bug fix)**: `create_cold_job` (de-dup — a queued/running `(user,model)` job returns the same id, no duplicate row), `run_cold_job` (background worker: queued→running→done writing `image_b64`/`via`; never raises — records a truncated error), `list_jobs` (metadata only, no image bytes), `reap_stale_jobs` (cold job stuck `running` past `COLD_JOB_MAX_WALLCLOCK_SECONDS=1200` → `error`).
- **Routes** (`routes/generate.py`): `POST /generate {image}` now non-blocking → `{job_id, status:"queued"}` + GC-safe `_spawn_bg(_run_cold_job_bg(...))` behind the per-`(user,model)` lock; `GET /generate/jobs`; `POST /generate/session/extend`.
- **Frontend (minimal — full panel is W.2)**: `client.ts` `runGenerate`→`{job_id}`; `runKaggleImage` now submits+polls `getJob` (cold Generate keeps working); `extendSession`/`listJobs`; `JobResult` gains `done_at`/`has_image`/`session_id`. `SessionPocPanel` renders PNG (FLUX) or echo text (SDXL); labels/heading generalized.

**Review:** code-reviewer initially FAIL — **CRITICAL**: `asyncio.create_task` keeps only a weak ref, so a GC cycle mid-Kaggle-call could collect the worker and strand a job at `running`. Fixed with a module-level `_bg_tasks` set + `add_done_callback` (`_spawn_bg`). WARNs fixed: `extend_session` live-check, `run_cold_job` error truncated to 300 chars + stderr log, `reap_stale_jobs` stderr log, `JobResult` fields, docstring. security-auditor PASS (only the public anon key is injected; service key never reaches the notebook; payload base64-injected).

**Decision (documented):** scoped per-session JWT (`supabase_jwt_secret`) **deferred within W.1**. Supabase's new `sb_publishable_*` key platform enforces RLS on the anon role and deprecates the legacy HS256 JWT-secret minting the plan assumed — so the permissive-anon RLS policy from W.0 is kept for the single-user trial. The scoped JWT becomes **mandatory before multi-user** (the new keys can't bypass RLS). A real SDXL serve-loop is a follow-up.

**Tests/build:** 132 backend passing (new `test_image_jobs.py`: create/de-dup, run_cold_job transitions, reap, list, non-blocking route, `/generate/jobs`; `test_generate.py`/`test_image_session.py` updated to the job contract + extend/FLUX-GPU-start tests). Frontend `npm run build` clean.
**Live verify pending:** Image Lab → FLUX → Start warm session → first image ~10 min, later images in seconds; Extend/Stop; cold Generate still returns an image (now job-polled).
**Commit:** (this commit)

### 2026-06-29 — W.2: Image Lab UI (session controls + Generations monitor) [imageLab]

**Built (frontend):**
- **Job-driven `ImageGenerator`** (`ImageLabPage.tsx`): submit → poll `getJob` → inline render. **Server-derived button state** — parent lifts a shared `listJobs` poll (all models); Generate is disabled while that model has a `queued`/`running` job, so a refresh / second tab can't fire a duplicate (the double-submit bug, now structurally prevented). Routes to `submitSessionJob` when a warm session is live (fast) else cold `runGenerate`. Added a local `submitting` guard for the click→response window.
- **`GenerationsPanel.tsx`** (new): collapsible monitor of all jobs across models/sessions, newest first — model badge, prompt, status chip (running spinner), relative time; done image jobs lazily fetch their PNG via `getJob` → thumbnail + View lightbox + Download. Server-backed → a navigated-away result reappears here (lost-result bug visibly fixed).
- **`SessionBar.tsx`** (new): per-model warm-session lifecycle — duration/cap picker, Start, live countdown, Extend +30, Stop, "session ended" CTA; re-attaches on mount via `getSessionStatus`; reports the live session up to the generator. `SessionPocPanel` deleted (superseded).

**Review:** code-reviewer PASS (0 critical). WARN fixes applied: (1) double-submit window → local `submitting` guard on top of the server-derived `busy`; (2) always-on 1s ticker → gated on a live countdown; (3) hardcoded lightbox download filename → derived from the image mime. Deferred (documented): frontend unit tests (project has none — gate is `npm run build`); GenerationsPanel lazy-image fan-out is bounded by the 30-job list cap (fine for the trial).

**Tests/build:** 132 backend tests still green (no backend change); frontend `npm run build` clean. **Phase W code-complete (W.0/W.1/W.2).**
**Live verify pending:** full warm-FLUX flow + monitor; refresh mid-generate → job re-attaches in the panel and Generate stays disabled. Then merge imageLab → dev. Scoped per-session JWT remains the gate before multi-user.
**Commit:** (this commit)

### 2026-06-29 — Fix: orphaned session jobs hung the panel/button (reap gap) [imageLab]

**Symptom:** Generate button stuck on "Generating (cold ~14 min)…" with nothing actually running on Kaggle; Generations showed "1 active". Root cause: a job submitted to an SDXL warm session stayed `queued` after the session **ended** (kernel exited before picking it up). `reap_stale_jobs` only handled cold jobs (`session_id` null) stuck `running` past the wall-clock — it never reaped **session** jobs whose session is dead, so the server-derived button state stayed disabled forever.
**Fix** (`core/image_session.py` `reap_stale_jobs`): now also (a) reaps cold jobs stuck in *any* active status (queued or running) past the wall-clock (a queued cold job whose in-process worker died on a backend restart), and (b) reaps queued/running **session** jobs whose session is no longer alive (ended/stopped/expired/stale heartbeat) → marked `error` "session ended before this job ran". Since `list_jobs` calls reap every poll, the panel + button self-heal within ~3s. The pre-existing stuck job was auto-cleared on redeploy.
**Tests:** 133 backend passing (added `test_reap_stale_jobs_reaps_jobs_of_dead_sessions`; renamed the cold reap test).
**Commit:** (this commit)

### 2026-06-29 — W.3: real SDXL warm serve-loop (warm sessions generate images, not echo) [imageLab]

**Why:** A warm session on the SDXL tab returned `ECHO: <prompt>` text — SDXL's session was wired to the W.0 CPU-echo POC (placeholder; "real SDXL serve-loop is a follow-up"). Only FLUX had a real warm serve-loop. User wants warm image generation for SDXL too (load once → generate many).
**Built:**
- `kaggle_templates/image_sdxl_session/notebook.ipynb` (new): mirrors the FLUX serve-loop structure (cell-0 payload + Supabase REST helpers; cell-1 install; cell-2 load SDXL ONCE via `AutoPipelineForText2Image.from_pretrained(..., torch_dtype=float16, use_safetensors=True, local_files_only=True).to("cuda")` → PATCH `ready`/`error`; cell-3 serve loop with SDXL inference 4 steps / guidance 0 / 512×768 → PATCH job done + PNG, `via kaggle:sdxl-session`).
- `core/image_models.py`: SDXL entry repointed — `session_template=image_sdxl_session`, `session_slug="pawn-sdxl-session"`, `session_gpu=True` (start_session then mounts the SDXL dataset + T4). Dropped the now-unused `KAGGLE_SESSION_POC_TEMPLATE`/`KAGGLE_SESSION_SLUG` imports (constants + session_poc notebook remain as the W.0 artifact, unreferenced).
- No frontend change — `ImageGenerator`/`GenerationsPanel` already render PNG vs text by MIME.
**Decision:** kept the cold path's 4 steps / guidance 0 / 512×768 for consistency (SDXL quality tuning is a separate pre-existing deferred item). The CPU echo POC stays in the repo (W.0 artifact) but is no longer user-facing — both SDXL + FLUX warm sessions are real now. SDXL loads in ~1–2 min (single T4, ~7GB fp16) vs FLUX ~10 min.
**Tests:** 134 backend passing — rewrote `test_start_session_inserts_row_and_pushes_cpu_notebook` → `test_start_session_sdxl_uses_gpu_serve_loop` (asserts GPU + dataset + `pawn-sdxl-session`); added `test_session_slug_titles_round_trip` (Kaggle title↔slug invariant for session slugs). The anon-key-only security test (runs on sdxl) still passes → no service key in the SDXL session push.
**Live verify pending:** SDXL → Connect → Warm session → Start → `Warm` in ~1–2 min → Generate returns an image in seconds (`via kaggle:sdxl-session`); thumbnails in Generations.
**Commit:** (this commit)
