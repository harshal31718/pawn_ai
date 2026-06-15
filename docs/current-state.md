# PAWN — Current State

Last updated: [date of last step]
Active step: Step 1 — Create the repo
Phase: Phase 1 — Foundation

---

## What's Built

Nothing yet. Starting from scratch.

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
