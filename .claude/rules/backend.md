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
