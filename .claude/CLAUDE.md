# PAWN — Personal AI Workspace

Multi-model BYOK chat app. One interface, multiple AI providers, transparent rate-limit
failover, persistent memory. Full project plan in `workspace/plan/` and decisions in `workspace/decisions/`. Current build state in
`workspace/current_state.md`. Build tracker in `workspace/status/build_tracker.md`.

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
6. Update `workspace/current_state.md` and `workspace/status/dev_log.md` after every step.

## Before Starting Any Work

1. Read `workspace/status/build_tracker.md` — find the current active step.
2. Read the relevant phase plan (e.g., `workspace/implemented_phases/phase_1_foundation.md` or `workspace/plan/phase_2_google_drive.md`).
3. Read `workspace/current_state.md` — understand what already exists.
4. Then implement.

## Multi-Agent Workflow

Use the `build-step` skill for implementing any numbered step. It automatically runs
code-reviewer, test-runner, security-auditor (if touching secrets), and build-validator.
Never manually chain agents — the skill handles it.
