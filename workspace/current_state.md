# PAWN — Current State

Last updated: 2026-06-22
Active step: Merge Phase 1.6 -> main
Phase: Phase 1.6 — Rate-Limit Resilience (Complete)

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
- [ ] Google Drive storage
- [ ] Encryption

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

None yet.

---

## Agents to Update This File

After every completed step, update:
1. "Last updated" date
2. "Active step" to the next step
3. Add new items to "What's Built"
4. Check off items in "What's Working"
5. Add any deferred issues
