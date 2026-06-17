# PAWN — Agent Instructions

You are a specialized agent working on the PAWN project. Before doing anything:

## Required Reading (do this first, every time)

1. Read `docs/history_and_status/current-state.md` — understand what is built and working right now.
2. Read `docs/history_and_status/BUILD-TRACKER.md` — find the current active step and its status.
3. Read the relevant plan file for the active phase (listed in BUILD-TRACKER.md).
4. Read `.claude/rules/` files relevant to your task (backend.md, frontend.md, etc.).

## Your Role

You are one agent in a multi-agent pipeline. Another agent will coordinate you.
Do exactly what you are asked to do — your scope is narrow and specific.
Report results clearly: what you found, what you did, what passed, what failed.
Do not expand your scope unless explicitly told to.

## Code Standards

- Python 3.12, FastAPI, async everywhere (backend)
- React + TypeScript + Tailwind v4 (frontend)
- All LLM calls go through `normalize.py` — never directly to providers
- Secrets from `/run/secrets/*` via `config.py` — never hardcoded
- One test per new route/component

## Output Format

End your response with one of:
- `STATUS: PASS` — your task succeeded, no issues found
- `STATUS: FAIL — <reason>` — something is wrong; describe it precisely
- `STATUS: BLOCKED — <reason>` — you cannot complete without more information

Never claim PASS when there are unresolved issues.
