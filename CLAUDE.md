# PAWN — Claude Code Quick Reference

This is the root-level pointer file for Claude Code. The full configuration lives in `.claude/`.

## Where Things Are

| What | Where |
|---|---|
| Full Claude Code instructions | `.claude/CLAUDE.md` |
| Backend rules | `.claude/rules/backend.md` |
| Frontend rules | `.claude/rules/frontend.md` |
| Security rules | `.claude/rules/security.md` |
| Testing rules | `.claude/rules/testing.md` |
| Agent definitions | `.claude/agents/` |
| Skills (build-step, etc.) | `.claude/skills/` |
| Build tracker | `workspace/status/build_tracker.md` |
| Current project state | `workspace/current_state.md` |
| Dev log | `workspace/status/dev_log.md` |
| Phase plans | `workspace/plan/` and `workspace/implemented_phases/` |
| Architecture decisions | `workspace/decisions/` |

## Before Starting Any Work

1. Read `.claude/CLAUDE.md` — full rules and constraints.
2. Read `workspace/status/build_tracker.md` — current active step.
3. Read `workspace/current_state.md` — what is already built.
4. Then implement.

## Key Rules (short form — full rules in `.claude/CLAUDE.md`)

- All LLM calls → `backend/app/core/normalize.py` only.
- Secrets → `/run/secrets/*` via `app/config.py`. Never hardcoded.
- Tests must pass before marking a step done.
- Never commit real files from `secrets/`.
- Update `workspace/current_state.md` and `workspace/status/dev_log.md` after every step.
