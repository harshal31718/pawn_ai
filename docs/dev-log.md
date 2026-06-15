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

### 2026-06-15 — Step 1: Create the Repo

**Built:** Directory skeleton — `backend/app/` (main.py, config.py, constants.py, routes/, core/), `backend/tests/`, `frontend/src/`. Stub files only; real content in Steps 2.5 and 4.
**Decisions:** Stub files use one-line comments pointing to the step that fills them in; avoids empty files while keeping the tree readable.
**Issues:** None.
**Tests:** N/A (directory structure only).
**Commit:** chore: init repo — directory structure

### 2026-06-15 — Step 2: Claude Code Config (done in scaffolding session)

**Built:** `.claude/CLAUDE.md`, `AGENTS.md`, `settings.json`, 4 rule files, 5 agent files, `skills/build-step/SKILL.md`. PreToolUse + PostToolUse hooks block secrets writes and force-push.
**Decisions:** Used plan/12-claude-setup-guide.md verbatim as the authoritative source for all .claude/ content.
**Issues:** None.
**Tests:** N/A.
**Commit:** chore: project scaffolding — .claude config, docs/, secrets pattern

### 2026-06-15 — Step 2.5: Docker Scaffolding

**Built:** `docker-compose.yml` with secrets block, `constants.py` (all paths from `DATA_DIR`), `config.py` (`read_secret()` checks `/run/secrets/` first then env var fallback), `backend/Dockerfile`, `backend/requirements.txt`, `frontend/Dockerfile`, 5 `secrets/*.example` files, empty gitignored placeholder secret files.
**Decisions:** Placeholder secret files created locally (gitignored) so `docker compose config` resolves without real keys. Dockerfiles are minimal stubs — full content in Steps 3 and 4.
**Issues:** None.
**Tests:** `docker compose config` validates cleanly; secrets mount at `/run/secrets/*`.
**Commit:** chore: docker scaffolding — compose, secrets-as-files, constants, config loader

### 2026-06-15 — Step 3: Static Chat UI

**Built:** React + Vite 8 + TypeScript + Tailwind v4 frontend. Components: `ChatWindow` (scrollable, auto-scroll to bottom), `MessageInput` (Enter sends, Shift+Enter newline), `Message` (user bubble right/dark, assistant left/light). `src/types.ts` defines `Message` and `ChatState`. Messages echo locally — no API calls yet.
**Decisions:** Used Tailwind v4 CSS-first setup (`@import "tailwindcss"` + `@tailwindcss/vite` plugin) — no config file needed. Upgraded Vite 6→8 to resolve esbuild high-severity vuln (0 vulns after fix). Module counter (`nextId`) is file-scoped to avoid state management overhead at this stage.
**Issues:** esbuild vuln in Vite 6 — fixed by upgrading to Vite 8 + @vitejs/plugin-react 6.
**Tests:** `npm run build` passes clean (tsc + vite build, 0 type errors, 0 vulns).
**Commit:** feat: static chat UI — message list, input, bubbles

### 2026-06-15 — Step 4: FastAPI Backend

**Built:** `main.py` (FastAPI + middleware stack), `middleware/security.py` (SecurityHeadersMiddleware: X-Frame-Options, CSP, X-Content-Type-Options, Referrer-Policy), `middleware/timeout.py` (45s timeout, SSE paths exempt), `exceptions.py` (ProviderError, NoEndpointError, HTTP handlers), `tests/test_health.py` (2 tests).
**Decisions:** Used `httpx2` instead of `httpx` to silence Starlette deprecation warning in TestClient. Exception handlers registered in `main.py` even though no provider routes exist yet — establishes the pattern for Step 6+.
**Issues:** `httpx` deprecation warning from Starlette TestClient — fixed by swapping to `httpx2`.
**Tests:** 2 passed (health returns ok, security headers present). Ran inside Docker container.
**Commit:** feat: fastapi backend — health check, middleware stack

### 2026-06-15 — Step 5: Connect Frontend to Backend

**Built:** `frontend/src/api/client.ts` — `healthCheck()` using `VITE_API_URL ?? localhost:8000` with `res.ok` guard. `App.tsx` updated with `useEffect` calling `healthCheck().then(console.log).catch(console.error)` on mount. Added `.env` to `.gitignore`. Fixed `tsconfig.app.json` missing `"types": ["vite/client"]` (caused TS2339 on `import.meta.env`).
**Decisions:** Kept the `localhost:8000` fallback (matches the plan spec) but added a comment to make the intent explicit. Added `res.ok` check and `.catch()` to surface backend errors clearly rather than swallowing them.
**Issues:** `import.meta.env` TypeScript error — fixed by adding `"types": ["vite/client"]` to `tsconfig.app.json`. Two WARNs from code reviewer (missing res.ok, missing .catch) — both fixed before commit.
**Tests:** `npm run build` passes (tsc + vite, 0 errors, 20 modules). Backend: 2/2 passing.
**Commit:** feat: frontend api client + health check wired

(entries added here as steps complete)
