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
**Commit:** chore: project scaffolding — .claude config, docs/, secrets pattern

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
