# PAWN for Google Antigravity / Gemini

Thin pointer. The single source of agent instructions is `.claude/AGENTS.md`
(rules, workflow, security, testing) and `.claude/CLAUDE.md` (project facts).
Skills live in `.claude/skills/` (`build-step`, `registry-refresh`); read them from there,
there is no separate copy under `.gemini/`.

Minimum to know before touching anything:

1. Read `workspace/current_state.md`, then `workspace/status/build_tracker.md`.
2. Module map and API reference: `workspace/CODEBASE_MAP.md`. Why things are the way they are: `workspace/decisions/change_log_2026.md`. Docs index: `workspace/README.md`.
3. Hard rules: all LLM calls through `backend/app/core/normalize.py`; secrets only via `/run/secrets/*` and `app/config.py`; SSE frames only via `app/events.py`; paths only via `app/constants.py`; tests must pass; never commit `secrets/`.
4. `main` is deploy-only (docs stripped). Promote only with `scripts/promote-to-main.sh`.
