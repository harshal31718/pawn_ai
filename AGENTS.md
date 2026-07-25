# PAWN — Agent Quick Reference

This is the root-level pointer file for external agents (non-Claude Code). The full agent instructions live in `.claude/AGENTS.md`.

## Where Things Are

| What | Where |
|---|---|
| Full agent instructions | `.claude/AGENTS.md` |
| Build tracker (current step) | `workspace/status/build_tracker.md` |
| Current project state | `workspace/current_state.md` |
| Dev log | `workspace/status/dev_log.md` |
| Phase plans | `workspace/plan/` and `workspace/implemented_phases/` |
| Architecture & decisions | `workspace/decisions/` |
| API reference | `workspace/api_reference.md` |
| Backend rules | `.claude/rules/backend.md` |
| Frontend rules | `.claude/rules/frontend.md` |
| Security rules | `.claude/rules/security.md` |
| Testing rules | `.claude/rules/testing.md` |
| Architecture rules | `.claude/rules/architecture.md` |
| Git workflow rules | `.claude/rules/git-workflow.md` |

## Required Reading Before Any Work

1. Read `workspace/current_state.md` — what is built and working right now.
2. Read `workspace/status/build_tracker.md` — the current active step and its status.
3. Read the relevant plan file for the active phase (path listed in build_tracker.md).
4. Read `.claude/rules/` files relevant to your task.

## Project Summary

PAWN is a multi-model BYOK chat app: React + Vite + TypeScript frontend, FastAPI backend,
SSE streaming, transparent rate-limit failover across providers, and persistent memory.

- Providers are URL-routed via `_detect_provider(url)` in `backend/app/core/llm_core.py`.
- All LLM calls go through `backend/app/core/normalize.py` — never call providers directly.
- Secrets come from Docker secret files at `/run/secrets/*` via `app/config.py`.
- Model registry lives in JSON files at `data/registry/` — data, not code.

## Agent Orchestration

Use the `build-step` skill for implementing any numbered step. It automatically runs
code-reviewer, test-runner, security-auditor (if touching secrets), and build-validator.
Never manually chain agents — the skill handles it.

Use parallel execution for independent operations — launch multiple agents simultaneously.

## Output Format

End every response with one of:
- `STATUS: PASS` — task succeeded, no issues found
- `STATUS: FAIL — <reason>` — something is wrong; describe it precisely
- `STATUS: BLOCKED — <reason>` — cannot complete without more information
