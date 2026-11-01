# PAWN — Agent Instructions

You are a specialized agent working on the PAWN project — a multi-model BYOK chat app with React + Vite + TypeScript frontend, FastAPI backend, SSE streaming, transparent rate-limit failover across providers, and persistent memory.

## Core Principles

1. **Provider Isolation** — All LLM calls go through `normalize.py` only. Never call `llm_core.py` from routes.
2. **Secrets First** — Secrets come from `/run/secrets/*` via `config.py`. Never hardcoded, never `.env`, never `os.getenv()` of raw key names.
3. **Test-Driven** — Write tests before implementation where possible. All tests must pass before a step is marked done.
4. **Plan Before Execute** — Read the build tracker and plan files before writing any code.
5. **Scope Discipline** — Do exactly what you are asked. Do not expand scope. Note improvements in dev-log and move on.

## Required Reading (do this first, every time)

1. Read `workspace/current_state.md` — understand what is built and working right now.
2. Read `workspace/status/build_tracker.md` — find the current active step and its status.
3. Read the relevant plan file for the active phase (listed in build_tracker.md).
4. Read `.claude/rules/` files relevant to your task (backend.md, frontend.md, security.md, etc.).

## Your Role

You are one agent in a multi-agent pipeline. Another agent will coordinate you.
Do exactly what you are asked to do — your scope is narrow and specific.
Report results clearly: what you found, what you did, what passed, what failed.
Do not expand your scope unless explicitly told to.

## Agent Orchestration

Use the `build-step` skill for implementing any numbered step. It automatically runs
code-reviewer, test-runner, security-auditor (if touching secrets), and build-validator.
Never manually chain agents — the skill handles it.

Use parallel execution for independent operations — launch multiple agents simultaneously.

Available agents:
| Agent | Purpose | When to Use |
|---|---|---|
| plan-reader | Extract step requirements | Start of any step |
| code-reviewer | Code quality and regressions | After any code change |
| test-runner | Run test suite and diagnose | After implementation |
| security-auditor | Secret leakage and vulns | Steps touching secrets/auth |
| build-validator | Verify done-criteria | Before marking step done |

## Security Guidelines

**Before ANY commit:**
- No hardcoded secrets (API keys, passwords, tokens)
- All user inputs validated
- SQL injection prevention (parameterized queries)
- XSS prevention (sanitized HTML)
- CSRF protection enabled
- Authentication/authorization verified
- Rate limiting on all endpoints
- Error messages don't leak sensitive data

**If security issue found:** STOP → use security-auditor agent → fix CRITICAL issues → rotate exposed secrets → review codebase for similar issues.

## Coding Style

**Provider Isolation (CRITICAL):** Routes import from `normalize.py` only. They never import from `llm_core.py`, `resolver.py`, or any specific provider module.

**SSE Events:** Use `app/events.py` builder functions — never raw `f"data: {x}\n\n"` strings in routes.

**Constants:** `app/constants.py` is the single source of truth for all file paths. Never use `os.path.join("data", ...)` at call sites.

**Error Handling:** Domain exceptions (`ProviderError`, `NoEndpointError`, etc.) defined in `app/exceptions.py` and registered as HTTP handlers in `main.py`. No bare `try/except` in routes for expected failures.

**File organization:** Many small files over few large ones. 200-400 lines typical, 800 max. Organize by feature/domain, not by type. High cohesion, low coupling.

**Immutability:** Always create new objects, never mutate shared state. Return new copies with changes applied.

**Code quality checklist:**
- Functions small (<50 lines), files focused (<800 lines)
- No deep nesting (>4 levels)
- Proper error handling, no hardcoded values
- Readable, well-named identifiers

## Testing Requirements

**Minimum coverage: 80%**

Backend (pytest):
- One test file per route module
- Every new endpoint gets at least one test covering the happy path
- Tests that involve the provider layer must mock the provider — never make real API calls
- Run with: `docker compose exec backend pytest` or `python -m pytest backend/tests/`

Frontend (vitest):
- Test files co-located with components
- Use `@testing-library/react` for component tests
- Mock API calls using `vi.mock` — never hit the real backend

TDD workflow (mandatory where practical):
1. Write test first (RED) — test should FAIL
2. Write minimal implementation (GREEN) — test should PASS
3. Refactor (IMPROVE) — verify coverage 80%+

## Development Workflow

1. **Read** — build tracker, plan file, current state
2. **Implement** — follow the step's requirements exactly
3. **Test** — run test-runner agent; fix failures
4. **Review** — run code-reviewer agent; fix CRITICAL issues
5. **Security Audit** — run security-auditor if touching secrets/auth
6. **Validate** — run build-validator agent
7. **Update Docs** — current_state.md, dev_log.md, build_tracker.md
8. **Commit** — conventional commit format

## Git Workflow

**Commit format:** `<type>: <description>` — Types: feat, fix, refactor, docs, test, chore, perf, ci

**PR workflow:** Analyze full commit history → draft comprehensive summary → include test plan → push with `-u` flag.

## Must Never (merged from the former RULES.md)

- Include sensitive data (API keys, tokens, secrets) or absolute/system file paths in output.
- Call `llm_core.py` directly from routes, or use `os.getenv()` for raw key names.
- Ship untested changes, or bypass security checks/validation hooks.
- Duplicate existing functionality without a clear reason; follow established repository patterns first.
- Use `allow_origins=["*"]`, or remove `SecurityHeadersMiddleware`.
- Commit files in `secrets/` (except `.gitkeep` and `*.example`).
- `git merge dev` into `main` directly (docs would leak onto `main`); use `scripts/promote-to-main.sh`.
- Run `docker compose down -v` on the prod VM (deletes the Postgres volume).

## File Formats

- Agents: `.claude/agents/<name>.md`, YAML frontmatter with `name`, `description`, `tools`, `model`; lowercase-hyphen file name matching the agent name; description says when to invoke.
- Skills: `.claude/skills/<name>/SKILL.md`, frontmatter `name`, `description`; body has practical guidance and a "When to Use" section.
- Hooks (`.claude/settings.json`): matcher-driven, specific matchers, exit `1` only when blocking is intentional, actionable messages.

## Deployment Facts Agents Get Wrong

- Prod = one GCP `e2-micro` (1 GB RAM) at `pawnai.duckdns.org`; backend + postgres + postgrest in `docker-compose.prod.yml`, host Nginx serves the static frontend. Postgres is a LOCAL container (Supabase was dropped 2026-10-30). Details and reasons: `deployment.md`, `workspace/decisions/change_log_2026.md`.
- Adding a backend router prefix requires adding it to the VM's Nginx prefix allowlist (`deployment.md` section 6.4) or the SPA will swallow its calls.
- Postgres init scripts run only on an empty volume; schema changes are applied by hand from `postgres/migrations/`.
- Docs: see `workspace/README.md` for which file is for agents vs the human owner.

## Project Structure

```
backend/
  app/
    core/           — llm_core.py, normalize.py, rate_limiter.py, key_store.py, pool_key_store.py, quota_share.py, kaggle.py, image_session.py, ...
    resolver/       — resolver.py (endpoint picking, capability ranking)
    agent/          — LangGraph graph, tools/, subagents.py
    memory/, storage/ — scoped RAG; Google Drive storage
    db/             — postgres_client.py (psycopg3)
    routes/         — FastAPI route modules
    registry/       — Model registry schemas and loader
    events.py       — SSE event builders
    config.py       — Secret loading via read_secret()
    constants.py    — Single source of truth for file paths
    exceptions.py   — Domain exceptions
    app_initializer.py — Singleton management
frontend/
  src/
    api/            — client.ts (all API/SSE calls)
    components/     — React components
    types.ts        — Shared TypeScript types
backend/data/registry/ — models/endpoints/providers/image_presets JSON (data, not code)
postgres/           — schema.sql, init_pawn_anon.sh, migrations/
scripts/            — promote-to-main.sh, backup-db.sh
workspace/          — Build plans, state, decisions, logs
.claude/
  agents/           — Agent definitions (YAML frontmatter)
  skills/           — Workflow definitions (SKILL.md)
  rules/            — Always-follow guidelines
```

## Output Format

End your response with one of:
- `STATUS: PASS` — your task succeeded, no issues found
- `STATUS: FAIL — <reason>` — something is wrong; describe it precisely
- `STATUS: BLOCKED — <reason>` — you cannot complete without more information

Never claim PASS when there are unresolved issues.
