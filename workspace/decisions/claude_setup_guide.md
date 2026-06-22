# PAWN — Claude Code Setup Guide
## Complete `.claude/` Configuration for /PAWN

This guide contains every file to create inside the `/PAWN` repo root before writing
any application code. Set this up first. Claude Code will use it for every session.

---

## Directory Map

```
/PAWN/
├── .claude/
│   ├── CLAUDE.md                  ← always loaded; main project context
│   ├── AGENTS.md                  ← universal rules for all non-Claude agents
│   ├── settings.json              ← permissions, hooks, allow-list
│   ├── rules/
│   │   ├── backend.md
│   │   ├── frontend.md
│   │   ├── testing.md
│   │   └── security.md
│   ├── agents/
│   │   ├── code-reviewer.md
│   │   ├── security-auditor.md
│   │   ├── test-runner.md
│   │   ├── plan-reader.md
│   │   └── build-validator.md
│   └── skills/
│       └── build-step/
│           └── SKILL.md
├── workspace/
│   ├── current-state.md           ← what's built and working RIGHT NOW (kept up to date)
│   ├── dev-log.md                 ← dated entry per step
│   └── api-reference.md           ← backend routes + SSE events (updated per step)
└── plan/                          ← copy the entire plan/ folder from the planning repo here
    ├── BUILD-TRACKER.md
    ├── 00-overview.md
    └── ... (all plan files)
```

---

## Step 0 — Copy the Plan

Before creating any `.claude/` files, copy the entire `plan/` folder into `/PAWN/plan/`.
The build tracker and phase plans are what agents read to know what to build.

```
/PAWN/plan/BUILD-TRACKER.md
/PAWN/plan/00-overview.md
/PAWN/plan/01-architecture.md
... etc
```

---

## `.claude/CLAUDE.md`

```markdown
# PAWN — Personal AI Workspace

Multi-model BYOK chat app. One interface, multiple AI providers, transparent rate-limit
failover, persistent memory. Full project plan in `plan/`. Current build state in
`workspace/current-state.md`. Build tracker in `plan/BUILD-TRACKER.md`.

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
6. Update `workspace/current-state.md` and `workspace/dev-log.md` after every step.

## Before Starting Any Work

1. Read `plan/BUILD-TRACKER.md` — find the current active step.
2. Read the relevant phase plan (e.g. `plan/04-phase1-foundation.md`).
3. Read `workspace/current-state.md` — understand what already exists.
4. Then implement.

## Multi-Agent Workflow

Use the `build-step` skill for implementing any numbered step. It automatically runs
code-reviewer, test-runner, security-auditor (if touching secrets), and build-validator.
Never manually chain agents — the skill handles it.
```

---

## `.claude/AGENTS.md`

This file is loaded by all subagents and specialized agents (not Claude itself).
Place it at `.claude/AGENTS.md`.

```markdown
# PAWN — Agent Instructions

You are a specialized agent working on the PAWN project. Before doing anything:

## Required Reading (do this first, every time)

1. Read `workspace/current-state.md` — understand what is built and working right now.
2. Read `plan/BUILD-TRACKER.md` — find the current active step and its status.
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
```

---

## `.claude/settings.json`

```json
{
  "permissions": {
    "allow": [
      "Bash(docker compose *)",
      "Bash(docker build *)",
      "Bash(pytest *)",
      "Bash(npm run *)",
      "Bash(npm install *)",
      "Bash(git status)",
      "Bash(git log *)",
      "Bash(git diff *)",
      "Bash(git add *)",
      "Bash(git commit *)",
      "Bash(git checkout *)",
      "Bash(git branch *)",
      "Bash(uvicorn *)",
      "Bash(python -m pytest *)",
      "Bash(npx *)"
    ]
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "powershell -NoProfile -Command \"$p=$input|Out-String|ConvertFrom-Json; if($p.tool_input.command -match 'secrets/[^.\\n]*[\\r\\n]|\\.env[^.]|git +push +.*--force'){Write-Error 'BLOCKED: touches secrets or force-push'; exit 2} else {exit 0}\""
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "powershell -NoProfile -Command \"$p=$input|Out-String|ConvertFrom-Json; $f=$p.tool_input.file_path; if($f -match 'secrets/' -and $f -notmatch '\\.example$' -and $f -notmatch '\\.gitkeep$'){Write-Error 'BLOCKED: writing to secrets/'; exit 2} else {exit 0}\""
          }
        ]
      }
    ]
  }
}
```

---

## `.claude/rules/backend.md`

```markdown
# Backend Rules

- Python 3.12, FastAPI, Pydantic v2, async everywhere.
- All LLM calls go through `app/core/normalize.py` → `llm_core.py`. Never inline in routes.
- All secrets come from `/run/secrets/*` via `app/config.py`. Never os.getenv of raw key names. Never hardcoded strings.
- Streaming responses use `StreamingResponse` with `text/event-stream`. Use `app/events.py` builder functions — never raw `f"data: {x}\n\n"` strings in routes.
- Provider isolation is absolute: routes import from `normalize.py` only. They never import from `llm_core.py`, `resolver.py`, or any specific provider module.
- `app/constants.py` is the single source of truth for all file paths. Never use `os.path.join("data", ...)` at call sites.
- All singletons built in `app/app_initializer.initialize_managers()` and injected via router factories. No module-level globals.
- `docker compose up` is the canonical way to run the stack. All code runs inside Docker.
- One test file per route module. Tests use `pytest` + `httpx.AsyncClient` + FastAPI `TestClient`.
- Domain exceptions (ProviderError, NoEndpointError, etc.) defined in `app/exceptions.py` and registered as HTTP handlers in `main.py`. No try/except in routes for expected failures.
```

---

## `.claude/rules/frontend.md`

```markdown
# Frontend Rules

- React + Vite + TypeScript + Tailwind v4. No additional UI libraries without explicit approval.
- All API calls and SSE streaming go through `src/api/client.ts`. Never use fetch() inline in components.
- All shared types go in `src/types.ts`.
- Components are small and single-purpose. If a component exceeds ~150 lines, split it.
- SSE parsing lives in `client.ts` `streamChat()`. Components receive typed callbacks, not raw event data.
- No hardcoded API URLs. Use `import.meta.env.VITE_API_URL` via the client module.
- All environment variables that are non-secret go in `.env.example` (committed). Real values go in `.env` (gitignored).
- `npm run build` must pass without errors or type errors before a step is marked done.
```

---

## `.claude/rules/testing.md`

```markdown
# Testing Rules

## Backend (pytest)

- One test file per route module: `tests/test_chat.py`, `tests/test_registry.py`, etc.
- Every new endpoint gets at least one test covering the happy path.
- Tests that involve the provider layer must mock the provider — never make real API calls in tests.
- Rate limiter tests use monkeypatched `time.time()` to control rolling windows and cooldown expiry.
- Run with: `docker compose exec backend pytest` or `python -m pytest backend/tests/`
- All tests must pass before a step is marked `[x]` in BUILD-TRACKER.md.

## Frontend (vitest)

- Test files co-located with components: `src/components/ModelSwitcher.test.tsx`.
- Use `@testing-library/react` for component tests.
- Mock API calls using `vi.mock` — never hit the real backend in frontend tests.
- Encryption tests (Phase 3+) run in `jsdom` environment with `vi.stubGlobal` for WebCrypto.

## What NOT to Test

- Internal implementation details (private functions, internal state).
- Docker networking or container startup.
- Real provider API calls (always mock these).
```

---

## `.claude/rules/security.md`

```markdown
# Security Rules

## Secrets

- API keys live as files in `secrets/`. Each key is its own file (e.g. `secrets/gemini_api_key`).
- Only `secrets/.gitkeep` and `secrets/*.example` are committed. All real key files are gitignored.
- `config.py` reads secrets via `read_secret(name)` which checks `/run/secrets/<name>` first, then env var fallback for local non-Docker runs.
- Never log API keys. Never include them in error messages. Never print them.
- Never put secrets in docker-compose.yml environment values. Use the `secrets:` block only.

## Code

- Never use `eval()` or `exec()` with user-supplied input.
- Never construct shell commands with user input. Use subprocess with list arguments if shell is needed.
- Sanitize filenames from user uploads before writing to disk (no path traversal).
- The security-auditor agent runs automatically on any step that touches secrets/, config.py, or auth-related code. Do not skip it.

## Headers

- `SecurityHeadersMiddleware` is always in the middleware stack. Never remove it.
- CORS is restricted to `http://localhost:5173` in development. Never use `allow_origins=["*"]`.
```

---

## `.claude/agents/code-reviewer.md`

```markdown
---
name: code-reviewer
description: >
  Reviews a completed step's diff for correctness, type safety, project conventions,
  and regressions. Runs automatically after every step implementation.
  Use proactively: after any code change before committing.
tools: Read, Grep, Glob
model: sonnet
---

You are a code reviewer for the PAWN project. You have been given a diff or a set of
changed files to review.

## What to Check

1. **Provider isolation** — do any routes import from llm_core.py directly? Flag it.
2. **Secrets** — any hardcoded API keys or secrets? Flag it.
3. **Type safety** — missing type hints in Python? Missing TypeScript types? Flag them.
4. **Tests** — does the diff add new endpoints without tests? Flag it.
5. **Constants** — any hardcoded paths like `"data/registry/..."` instead of using constants.py? Flag it.
6. **Event builders** — any raw `f"data: ..."` SSE strings in routes instead of `events.py` functions? Flag it.
7. **Error handling** — are domain exceptions used, or are there bare `try/except Exception`? Flag bare catches.
8. **Naming** — do names match the plan's conventions? (e.g. `EndpointRateLimiter` not `RateLimiter`)

## Output Format

List each finding as:
`[SEVERITY] file:line — description`

Severity: `CRITICAL` (must fix before commit) / `WARN` (should fix) / `NOTE` (optional)

End with: `STATUS: PASS` (no CRITICAL issues) or `STATUS: FAIL — N critical issues found`
```

---

## `.claude/agents/security-auditor.md`

```markdown
---
name: security-auditor
description: >
  Audits code for API key leakage, secret handling violations, and security issues.
  Runs automatically on any step touching secrets/, config.py, auth, or uploads.
tools: Read, Grep, Glob
model: sonnet
---

You are a security auditor for the PAWN project.

## What to Check

1. **Secrets in code** — grep for API key patterns (`sk-`, `AIza`, hardcoded long strings). Flag any found.
2. **secrets/ gitignore** — only `.gitkeep` and `*.example` should be tracked. Real key files must be absent.
3. **config.py compliance** — all keys read via `read_secret()`. No `os.getenv("GEMINI_API_KEY")` patterns.
4. **Logging** — no `print()` or `logger` calls that could leak key values.
5. **Error messages** — do error responses include raw provider error bodies that might contain auth info?
6. **File uploads** — if the diff touches upload handling, check for path traversal (user-supplied filename used in open() directly).
7. **CORS** — `allow_origins` must not be `["*"]`.

## Output Format

`[CRITICAL|WARN] file:line — description`

End with: `STATUS: PASS` or `STATUS: FAIL — <summary>`

CRITICAL means the step cannot be committed until fixed.
```

---

## `.claude/agents/test-runner.md`

```markdown
---
name: test-runner
description: >
  Runs the test suite and diagnoses failures. Runs automatically after every step
  implementation. Use after any code change.
tools: Bash, Read
model: sonnet
---

You are the test runner for the PAWN project.

## What to Do

1. Run backend tests: `docker compose exec backend python -m pytest -v`
2. If frontend tests exist: `docker compose exec frontend npm test -- --run`
3. For each failing test, show:
   - The test name and file
   - The exact assertion that failed
   - The root cause (read the relevant source file if needed)
   - A minimal fix (describe it; do not apply it yourself)

## Output Format

Show full test output. Then summarize:
- Tests run: N
- Passed: N
- Failed: N (list names)

End with: `STATUS: PASS` (all tests pass) or `STATUS: FAIL — N tests failing`

If the test suite cannot run at all (import error, Docker not running, etc.), report
`STATUS: BLOCKED — <reason>` and describe what needs to be fixed first.
```

---

## `.claude/agents/plan-reader.md`

```markdown
---
name: plan-reader
description: >
  Reads the plan files and BUILD-TRACKER to answer "what does this step require?"
  Use at the start of any step to extract requirements, file list, and demo criteria.
tools: Read, Glob
model: haiku
---

You are a plan reader for the PAWN project. You read plan documents and extract
structured information about a specific build step.

## What to Do

1. Read `plan/BUILD-TRACKER.md` to find the current active step.
2. Read the relevant phase plan file (e.g. `plan/04-phase1-foundation.md`).
3. Read `workspace/current-state.md` to understand what already exists.

## Output Format

Return a structured summary:

**Step:** [step number and name]
**Phase plan file:** [filename]
**Goal:** [one sentence]
**Demo (done-when):** [what must work]
**Files to create:** [list]
**Files to modify:** [list]
**Tests required:** [what must be tested]
**Agents needed:** [which agents should run on this step]
**Security audit needed:** [yes/no — yes if touching secrets/, config.py, auth, uploads]

End with: `STATUS: PASS`
```

---

## `.claude/agents/build-validator.md`

```markdown
---
name: build-validator
description: >
  Validates that a completed step meets its done-criteria from the plan.
  Runs as the final check before updating BUILD-TRACKER.md.
tools: Read, Bash, Grep
model: sonnet
---

You are the build validator for the PAWN project. You are given a step number and
you verify that it is truly complete.

## What to Do

1. Read the step's requirements from the relevant phase plan file.
2. Read the step's demo criteria.
3. For each criterion:
   - Check that the required files exist
   - Check that required tests exist and pass (call test-runner agent or check output)
   - Verify naming conventions match the plan (grep for expected class/function names)
4. Check `workspace/current-state.md` has been updated to reflect the completed step.
5. Check `workspace/dev-log.md` has a dated entry for this step.

## Output Format

List each criterion:
`[PASS|FAIL] — criterion description`

End with:
`STATUS: PASS — Step N is complete. Ready to update BUILD-TRACKER.md.`
or
`STATUS: FAIL — Step N incomplete. Issues: [list]`

Do NOT update BUILD-TRACKER.md yourself. Report the result and let the orchestrating
agent do that.
```

---

## `.claude/skills/build-step/SKILL.md`

```markdown
---
name: build-step
description: >
  Implements one numbered build step end to end using multiple agents automatically.
  Use when the user says "start step N", "build step N", or "implement step N".
---

## When This Skill Runs

Triggered by: "start step [N]", "build step [N]", "implement [step name]", "do step [N]"

## What Happens (Multi-Agent Pipeline)

The skill runs agents automatically in this order:

### Phase A — Read the Step (plan-reader agent)
Run the `plan-reader` agent to extract:
- Exact requirements for the step
- Files to create/modify
- Demo criteria
- Whether security audit is needed

### Phase B — Implement
Implement the step based on plan-reader's output:
1. Create/modify all files listed
2. Follow `.claude/rules/backend.md` and `.claude/rules/frontend.md`
3. Write tests as specified
4. Do not implement anything beyond the step's scope

### Phase C — Test (test-runner agent)
Run the `test-runner` agent:
- If STATUS: PASS → continue
- If STATUS: FAIL → fix the failing tests, then re-run test-runner
- If STATUS: BLOCKED → report to the user; do not continue

### Phase D — Review (code-reviewer agent)
Run the `code-reviewer` agent on the diff:
- If STATUS: PASS → continue
- If STATUS: FAIL → fix CRITICAL issues, re-run reviewer
- WARN issues: fix if easy; note them in dev-log if deferred

### Phase E — Security Audit (security-auditor agent, conditional)
Run only if plan-reader flagged "Security audit needed: yes".
- If STATUS: PASS → continue
- If STATUS: FAIL → fix all CRITICAL security issues before proceeding

### Phase F — Validate (build-validator agent)
Run the `build-validator` agent:
- If STATUS: PASS → proceed to Phase G
- If STATUS: FAIL → fix missing items, re-run validator

### Phase G — Update Docs
1. Update `workspace/current-state.md`: add what was built in this step
2. Append a dated entry to `workspace/dev-log.md`
3. Update `plan/BUILD-TRACKER.md`: mark the step `[x]`
4. Commit: `git commit -m "feat: [step description]"`

## Output to User

After all phases complete, report:
- What was built (files created/modified)
- Test results (N passed)
- Any deferred WARN issues
- The commit hash
- What the next step is (from BUILD-TRACKER.md)

## Constraints

- Never skip Phase C (tests) or Phase D (review).
- Never mark a step `[x]` if tests are failing.
- Never implement beyond the current step's scope. If you see something that could
  be improved outside the step, note it in dev-log and move on.
- If any agent returns BLOCKED, stop and report to the user. Do not guess.
```

---

## `workspace/current-state.md` (initial content)

Create this file in `/PAWN/workspace/current-state.md` before starting Step 1:

```markdown
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
```

---

## `workspace/dev-log.md` (initial content)

```markdown
# PAWN — Development Log

One dated entry per step. Each entry is a brief record of what was built,
what decisions were made, and any issues encountered.
This becomes your interview script and project history.

---

## Format

### [YYYY-MM-DD] — Step N: [Step Name]

**Built:** [brief description]
**Decisions:** [any non-obvious choices made]
**Issues:** [anything that took time or was tricky]
**Tests:** [N passing]
**Commit:** [hash]

---

(entries added here as steps complete)
```

---

## Final Checklist Before Writing Code

- [ ] `/PAWN/plan/` contains all plan files (copy from planning repo)
- [ ] `/PAWN/.claude/CLAUDE.md` created
- [ ] `/PAWN/.claude/AGENTS.md` created
- [ ] `/PAWN/.claude/settings.json` created
- [ ] `/PAWN/.claude/rules/` — all 4 rule files created
- [ ] `/PAWN/.claude/agents/` — all 5 agent files created
- [ ] `/PAWN/.claude/skills/build-step/SKILL.md` created
- [ ] `/PAWN/workspace/current-state.md` created with initial content
- [ ] `/PAWN/workspace/dev-log.md` created with initial content
- [ ] `claude` runs in `/PAWN` without errors
- [ ] Hook in `settings.json` blocks `secrets/real_key` writes (test it)

Once all boxes are checked: run `build-step` skill and say **"start step 1"**.
