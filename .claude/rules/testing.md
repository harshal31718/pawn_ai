# Testing Rules

## Backend (pytest)

- One test file per route module: `tests/test_chat.py`, `tests/test_registry.py`, etc.
- Every new endpoint gets at least one test covering the happy path.
- Tests that involve the provider layer must mock the provider — never make real API calls in tests.
- Rate limiter tests use monkeypatched `time.time()` to control rolling windows and cooldown expiry.
- Run with: `docker compose exec backend pytest` or `python -m pytest backend/tests/`
- All tests must pass before a step is marked `[x]` in BUILD-TRACKER.md.
- Full suite parallel: `docker compose exec backend pytest -n auto`

## Frontend (vitest)

- Test files co-located with components: `src/components/ModelSwitcher.test.tsx`.
- Use `@testing-library/react` for component tests.
- Mock API calls using `vi.mock` — never hit the real backend in frontend tests.
- Encryption tests (Phase 3+) run in `jsdom` environment with `vi.stubGlobal` for WebCrypto.

## What NOT to Test

- Internal implementation details (private functions, internal state).
- Docker networking or container startup.
- Real provider API calls (always mock these).

## Gate Scoping (keep gates proportional to the diff)

- Gates apply to what the step actually changed. Backend-only diff → backend pytest only; frontend-only diff → `tsc` + `npm run build` only. Do NOT run the other stack's gate "just to confirm" — REST+SSE is the only coupling, and the contract is covered by the changed side's tests.
- During iteration inside a step, run only the affected test files; the FULL backend suite runs once at step completion (before marking `[x]`), not on every edit.
- A cross-stack gate is required only when the step changed a shared contract surface: SSE event shapes (`events.py` / `client.ts`), request/response models, or route paths.
- Full-suite runs use `pytest -n auto` (pytest-xdist) inside the backend container: `docker compose exec backend pytest -n auto`. Scoped single-file runs during iteration don't need `-n`.

## TDD Workflow (where practical)

1. Write test first (RED) — test should FAIL
2. Write minimal implementation (GREEN) — test should PASS
3. Refactor (IMPROVE) — verify coverage 80%+

Troubleshoot failures: check test isolation → verify mocks → fix implementation (not tests, unless tests are wrong).

## Coverage

- Minimum coverage: 80%
- Backend: `docker compose exec backend pytest --cov=app --cov-report=term-missing`
- Frontend: `docker compose exec frontend npm run test:coverage`
