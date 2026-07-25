# Architecture Rules

## API Response Format

Use consistent envelope pattern:
```json
{
  "success": true,
  "data": { ... },
  "error": null,
  "pagination": { "page": 1, "per_page": 20, "total": 100 }
}
```

## Repository Pattern

Encapsulate data access behind standard interface (findAll, findById, create, update, delete). Business logic depends on abstract interface, not storage mechanism.

## Provider Isolation

Routes → `normalize.py` → `llm_core.py` → providers. This chain is absolute. Routes never bypass normalize.py.

## Singleton Management

All singletons built in `app/app_initializer.initialize_managers()` and injected via router factories. No module-level globals. No `import` side effects.

## SSE Architecture

- Backend: `app/events.py` builder functions produce typed SSE events.
- Frontend: `src/api/client.ts` `streamChat()` parses SSE and delivers typed callbacks.
- Contract: SSE event shapes are the coupling point between stacks.

## File Paths

`app/constants.py` is the single source of truth for all file paths. Never use `os.path.join("data", ...)` at call sites.

## Error Flow

Domain exceptions (`app/exceptions.py`) → registered as HTTP handlers in `main.py` → consistent error responses. No bare `try/except` in routes.

## State Management

- Backend: No global mutable state. Singletons are created once and injected.
- Frontend: React state + hooks. No external state management library without approval.

## Scaling Principles

- Many small files over few large ones. 200-400 lines typical, 800 max.
- Organize by feature/domain, not by type.
- High cohesion, low coupling.
- Always create new objects, never mutate shared state.
