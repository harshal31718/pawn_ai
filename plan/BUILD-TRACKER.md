# PAWN — Build Tracker

Source of truth for *what to build* is the relevant phase plan file in `plan/`.
This file tracks *where we are*. Update it after every step — mark `[x]` only when
tests pass and the step's demo works.

The Claude Code instance inside `/PAWN` uses this file to know what to build next.
Agents should read this before starting any work.

Legend: `[ ]` not started · `[~]` in progress · `[x]` done & verified

---

## Current Status

**Active phase:** Phase 1 — Foundation
**Active step:** Step 7 — Typed SSE events
**Last completed:** Step 6 — First real AI response
**Branch:** dev

---

## Phase 1 — Foundation
*Plan reference: `plan/04-phase1-foundation.md`*

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

- [ ] **Step 7 — Typed SSE events**
  `events.py` builder functions. All event types wired.
  Demo: Network tab shows `{"type": "token", "delta": "..."}`.

- [ ] **Step 8 — Conversation history**
  Full message array forwarded per request.
  Demo: say a name, later ask what it is — AI knows.

- [ ] **Step 9 — Multi-provider**
  Add Cerebras. URL-routing shape in `normalize.py`.
  Demo: both Gemini and Cerebras stream real replies.

- [ ] **Step 10 — Model switcher UI**
  Hardcoded dropdown, provider sent per message.
  Demo: switch mid-conversation, context intact.

- [ ] **Step 11 — Basic RAG**
  `POST /upload`, whole-doc injection, attach button in UI.
  Demo: upload a doc, ask about it — AI answers from it.

---

## Phase 1.5 — Memory & Agent
*Plan reference: `plan/05-phase1.5-memory-agent.md`*

- [ ] **Step 12 — Multi-chat persistence**
  Backend source of truth. `data/conversations/<uuid>/`. CRUD endpoints. Sidebar UI.
  Demo: two chats with independent history, survive restarts. Auto-title fires.

- [ ] **Step 13 — Complete typed SSE events**
  All event types dispatched and routed in `streamChat`. Frontend callbacks wired.
  Demo: all event types appear in Network tab; UI handles each.

- [ ] **Step 14 — Per-chat memory summaries**
  Rolling `summary.md` per conversation. Threshold-triggered summarization.
  Demo: 30-message chat stays coherent; `summary.md` written to disk.

- [ ] **Step 15 — RAG over memory**
  `data/memory/index.json`. `text-embedding-004` embed interface. Brute-force cosine.
  Demo: fact from chat A surfaces in chat B via retrieval.

- [ ] **Step 16 — LangGraph agent**
  `StateGraph` with 5 nodes. JSON/ReAct protocol. Trace panel in UI.
  Demo: complex question → trace shows plan/retrieve/draft/critique/answer.

---

## Phase 1.6 — Rate-Limit Resilience
*Plan reference: `plan/06-phase1.6-rate-limit.md`*
*Branch: `dev/rate-limit-resilience`*

- [ ] **Step R1 — Registry foundation**
  `models.json` + `endpoints.json` seeded. `loader.py`. `GET /registry/models`.
  New secrets: huggingface, github, openrouter.
  Demo: `GET /registry/models` returns the full catalog.

- [ ] **Step R2 — Rate limiter**
  `EndpointRateLimiter`: rolling windows, 90% threshold, cooldowns, dead-host.
  Demo: unit tests show endpoint flips unavailable at ≥90% and recovers.

- [ ] **Step R3 — Resolver + normalize contract change**
  `Resolver.pick(model_id)`. `normalize.chat_stream(model_id, messages)`.
  `ChatRequest` takes `model_id` only. Agent swaps to `PURPOSE_TO_LEVEL`.
  Demo: force priority-1 past 90% → next endpoint serves reply; `provider_switch` emitted.

- [ ] **Step R4 — Frontend wiring**
  `ModelSwitcher` fetches from API. `provider_switch` inline notice. Provider badge.
  Demo: dropdown shows Fast/Balanced/Research groups; failover notice appears.

- [ ] **Merge Phase 1.6 → main**

---

## Phase 2 — Google Drive
*Plan reference: `plan/07-phase2-drive.md`*

- [ ] **P2-1** — Drive API wired; conversation logs read/written to Drive.
- [ ] **P2-2** — User memory file on Drive; auto-injected into context.
- [ ] **P2-3** — Uploaded docs stored on Drive.

---

## Phase 3 — Encryption
*Plan reference: `plan/08-phase3-encryption.md`*

- [ ] **P3-1** — WebCrypto AES-256-GCM; all personal Drive files encrypted in browser.

---

## Phase 4 — Multi-User / Auth
*Plan reference: `plan/09-phase4-multiuser.md`*

- [ ] **P4-1** — Google OAuth2; multi-user sessions; per-user Drive isolation.
- [ ] **P4-2** — Settings panel; custom agent configs; capability + tag routing.

---

## Working Agreement

- One step per session. Pause and review the diff before moving to the next.
- Read the phase plan file before starting a step.
- Tests must pass before marking `[x]`. No exceptions.
- Update this file and `docs/dev-log.md` at the end of every step.
- The step is done when its demo works, not just when the code compiles.
