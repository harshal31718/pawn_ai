# Frontend Rules

## Stack

- React + Vite + TypeScript + Tailwind v4. No additional UI libraries without explicit approval.

## API Layer

- All API calls and SSE streaming go through `src/api/client.ts`. Never use `fetch()` inline in components.
- No hardcoded API URLs. Use `import.meta.env.VITE_API_URL` via the client module.
- SSE parsing lives in `client.ts` `streamChat()`. Components receive typed callbacks, not raw event data.

## Types

- All shared types go in `src/types.ts`.

## Components

- Components are small and single-purpose. If a component exceeds ~150 lines, split it.
- No emojis in codebase.
- Prioritize modular code over mega-files.

## Environment Variables

- All environment variables that are non-secret go in `.env.example` (committed). Real values go in `.env` (gitignored).

## Testing

- Test files co-located with components: `src/components/ModelSwitcher.test.tsx`.
- Use `@testing-library/react` for component tests.
- Mock API calls using `vi.mock` — never hit the real backend in frontend tests.
- Encryption tests (Phase 3+) run in `jsdom` environment with `vi.stubGlobal` for WebCrypto.

## Build Verification

- `npm run build` must pass without errors or type errors before a step is marked done.
- Run `docker compose exec frontend npx tsc --noEmit` for type checking.
- Run `docker compose exec frontend npm run build` for build verification.

## Code Quality

- Functions small (<50 lines), files focused (<800 lines).
- No deep nesting (>4 levels).
- Proper error handling, no hardcoded values.
- Readable, well-named identifiers.
- Always create new objects, never mutate shared state.
