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
