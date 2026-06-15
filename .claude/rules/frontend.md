# Frontend Rules

- React + Vite + TypeScript + Tailwind v4. No additional UI libraries without explicit approval.
- All API calls and SSE streaming go through `src/api/client.ts`. Never use fetch() inline in components.
- All shared types go in `src/types.ts`.
- Components are small and single-purpose. If a component exceeds ~150 lines, split it.
- SSE parsing lives in `client.ts` `streamChat()`. Components receive typed callbacks, not raw event data.
- No hardcoded API URLs. Use `import.meta.env.VITE_API_URL` via the client module.
- All environment variables that are non-secret go in `.env.example` (committed). Real values go in `.env` (gitignored).
- `npm run build` must pass without errors or type errors before a step is marked done.
