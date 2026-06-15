# PAWN — Current State

Last updated: 2026-06-15
Active step: Step 7 — Typed SSE events
Phase: Phase 1 — Foundation

---

## What's Built

- Step 1: repo directory structure — `backend/app/`, `backend/tests/`, `frontend/src/`, `.gitignore`, `.dockerignore`, `secrets/.gitkeep`
- Step 2: `.claude/` config — CLAUDE.md, AGENTS.md, rules (4), agents (5), skills/build-step, settings.json with hooks
- Step 2.5: Docker scaffolding — `docker-compose.yml`, `constants.py`, `config.py`, secrets-as-files pattern, `backend/Dockerfile`, `backend/requirements.txt`, `frontend/Dockerfile`, 5 `secrets/*.example` files
- Step 3: Static chat UI — React + Vite 8 + TypeScript + Tailwind v4; `ChatWindow`, `MessageInput`, `Message` components; `types.ts`; messages echo locally; `npm run build` passes clean
- Step 4: FastAPI backend — `main.py` with full middleware stack (GZip, Timeout, SecurityHeaders, CORS), `exceptions.py` (ProviderError, NoEndpointError + handlers), `middleware/security.py`, `middleware/timeout.py`; `GET /health` → `{"status":"ok"}`; 2 tests passing
- Step 5: Frontend ↔ backend connected — `src/api/client.ts` with `healthCheck()` (VITE_API_URL, res.ok check), `App.tsx` calls it on mount with `.then(console.log).catch(console.error)`; `.env` gitignored; `npm run build` passes
- Step 6: First real AI response — `llm_core.py` (stream_llm async generator, OAI-compat SSE parsing, shared httpx client with lifespan shutdown), `routes/chat.py` (ChatMessage schema, POST /chat SSE), `streamChat()` in client.ts, streaming state + token accumulation in App.tsx; 4 tests passing

---

## What's Working

- [ ] Docker stack running
- [ ] Backend health check
- [ ] Frontend serving
- [ ] Gemini streaming
- [ ] Cerebras streaming
- [ ] Model switcher
- [ ] Conversation persistence
- [ ] Memory RAG
- [ ] LangGraph agent
- [ ] Rate-limit failover
- [ ] Google Drive storage
- [ ] Encryption

---

## Key File Locations

- Backend entry: `backend/app/main.py`
- Provider routing: `backend/app/core/normalize.py`
- LLM core: `backend/app/core/llm_core.py`
- Rate limiter: `backend/app/core/rate_limiter.py`
- Resolver: `backend/app/resolver/resolver.py`
- Registry loader: `backend/app/registry/loader.py`
- Constants (all paths): `backend/app/constants.py`
- Config (secrets): `backend/app/config.py`
- SSE events: `backend/app/events.py`
- Frontend API client: `frontend/src/api/client.ts`

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
