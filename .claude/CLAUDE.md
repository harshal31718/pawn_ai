# PAWN — Personal AI Workspace

Multi-model BYOK chat app. One interface, multiple AI providers, transparent rate-limit
failover, persistent memory. Full project plan in `docs/blueprints/` and `docs/specifications/`. Current build state in
`docs/history_and_status/current-state.md`. Build tracker in `docs/history_and_status/BUILD-TRACKER.md`.

## What This Is

- Frontend: React + Vite + TypeScript + Tailwind v4
- Backend: FastAPI (Python 3.12), async, SSE streaming
- Providers: URL-routed via `_detect_provider(url)` in `backend/app/core/llm_core.py`
- All providers use the OpenAI-compatible wire format (including Google's OAI-compat endpoint)
- Model registry: JSON files in `data/registry/` — data, not code
- Secrets: Docker secret files at `/run/secrets/*` — never .env, never hardcoded

## Absolute Rules (Never Break These)

1. All LLM calls go through `backend/app/core/normalize.py` only. Never call llm_core directly from routes.
2. Secrets come from `/run/secrets/*` via `app/config.py`. Never inline keys. Never `.env`.
3. Tests must pass before a step is marked done. No exceptions.
4. Never commit files in `secrets/` (except `.gitkeep` and `*.example`).
5. Frontend and backend communicate via REST + SSE only. No shared code or imports.
6. Update `docs/current-state.md` and `docs/dev-log.md` after every step.

## Before Starting Any Work

1. Read `docs/history_and_status/BUILD-TRACKER.md` — find the current active step.
2. Read the relevant phase plan (e.g., `docs/blueprints/04-phase1-foundation.md`).
3. Read `docs/history_and_status/current-state.md` — understand what already exists.
4. Then implement.

## Multi-Agent Workflow

Use the `build-step` skill for implementing any numbered step. It automatically runs
code-reviewer, test-runner, security-auditor (if touching secrets), and build-validator.
Never manually chain agents — the skill handles it.
