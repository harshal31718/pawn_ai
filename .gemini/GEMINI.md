# PAWN for Google Antigravity

This file provides Google Antigravity with the baseline PAWN workflow, review standards, and security checks.

## Project Overview

PAWN is a multi-model BYOK chat app: React + Vite + TypeScript frontend, FastAPI backend, SSE streaming, transparent rate-limit failover across providers, and persistent memory.

- **Frontend:** React + Vite + TypeScript + Tailwind v4
- **Backend:** FastAPI (Python 3.12), async everywhere, SSE streaming
- **Providers:** URL-routed via `_detect_provider(url)` in `backend/app/core/llm_core.py`
- **Wire format:** All providers use OpenAI-compatible wire format
- **Model registry:** JSON files in `data/registry/` — data, not code
- **Secrets:** Docker secret files at `/run/secrets/*` — never `.env`, never hardcoded

## Core Workflow

1. Read `workspace/status/build_tracker.md` — find the current active step.
2. Read the relevant phase plan file.
3. Read `workspace/current_state.md` — understand what already exists.
4. Implement the step following the plan exactly.
5. Run tests before marking a step done.
6. Update docs after every step.

## Absolute Rules

1. All LLM calls go through `backend/app/core/normalize.py` only. Never call `llm_core.py` directly from routes.
2. Secrets come from `/run/secrets/*` via `app/config.py`. Never inline keys. Never `.env`.
3. Tests must pass before a step is marked done. No exceptions.
4. Never commit files in `secrets/` (except `.gitkeep` and `*.example`).
5. Frontend and backend communicate via REST + SSE only. No shared code or imports.
6. Use `app/events.py` SSE builder functions — never raw `f"data: {x}\n\n"` in routes.
7. `app/constants.py` is the single source of truth for all file paths.

## Coding Standards

- Prefer immutable updates over in-place mutation.
- Keep functions small and files focused (<800 lines).
- Validate user input at boundaries.
- Never hardcode secrets.
- Fail loudly with clear error messages instead of silently swallowing problems.
- Domain exceptions (`ProviderError`, `NoEndpointError`, etc.) defined in `app/exceptions.py`.

## Security Checklist

Before any commit:

- No hardcoded API keys, passwords, or tokens
- All external input validated
- Parameterized queries for database writes
- Sanitized HTML output where applicable
- Authz/authn checked for sensitive paths
- Error messages scrubbed of sensitive internals
- CORS restricted (never `allow_origins=["*"]`)
- `SecurityHeadersMiddleware` always in the stack

## Agent Orchestration

Use the `build-step` skill for implementing any numbered step. It automatically runs code-reviewer, test-runner, security-auditor (if touching secrets), and build-validator. Never manually chain agents.

## Delivery Standards

- Use conventional commits: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`
- Run targeted verification for touched areas before shipping
- Prefer contained local implementations over adding new third-party runtime dependencies
- Update `workspace/current_state.md` and `workspace/status/dev_log.md` after every step

## Key Files

- `AGENTS.md` — repo-wide operating rules
- `.claude/skills/` — workflow definitions (build-step, registry-refresh)
- `.claude/agents/` — specialized subagents
- `.claude/rules/` — always-follow guidelines (backend, frontend, security, testing, architecture, git-workflow)
