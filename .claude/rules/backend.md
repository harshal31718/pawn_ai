# Backend Rules

## Stack

- Python 3.12, FastAPI, Pydantic v2, async everywhere.
- `docker compose up` is the canonical way to run the stack. All code runs inside Docker.

## Provider Isolation (CRITICAL)

- All LLM calls go through `app/core/normalize.py` → `llm_core.py`. Never inline in routes.
- Routes import from `normalize.py` only. They never import from `llm_core.py`, `resolver.py`, or any specific provider module.
- Provider detection is handled by `_detect_provider(url)` in `llm_core.py`.
- All providers use the OpenAI-compatible wire format (including Google's OAI-compat endpoint).

## Secrets

- All secrets come from `/run/secrets/*` via `app/config.py`. Never `os.getenv("RAW_KEY_NAME")`. Never hardcoded strings.
- Never log API keys. Never include them in error messages. Never print them.
- Never put secrets in docker-compose.yml environment values. Use the `secrets:` block only.

## SSE Events

- Streaming responses use `StreamingResponse` with `text/event-stream`.
- Use `app/events.py` builder functions — never raw `f"data: {x}\n\n"` strings in routes.
- Frontend parses SSE in `src/api/client.ts` `streamChat()`. Components receive typed callbacks.

## Constants & Paths

- `app/constants.py` is the single source of truth for all file paths. Never use `os.path.join("data", ...)` at call sites.

## Singletons & DI

- All singletons built in `app/app_initializer.initialize_managers()` and injected via router factories. No module-level globals.

## Error Handling

- Domain exceptions (`ProviderError`, `NoEndpointError`, etc.) defined in `app/exceptions.py` and registered as HTTP handlers in `main.py`.
- No bare `try/except Exception` in routes for expected failures. Use domain exceptions.

## Model Registry

- Model registry lives in JSON files at `data/registry/` — data, not code.
- Pydantic schemas in `backend/app/registry/schemas.py` and loader in `backend/app/registry/loader.py` are the contract.
- Never delete model/endpoint entries — use `active: false` for deactivation.

## Testing

- One test file per route module: `tests/test_chat.py`, `tests/test_registry.py`, etc.
- Tests use `pytest` + `httpx.AsyncClient` + FastAPI `TestClient`.
- Tests that involve the provider layer must mock the provider — never make real API calls in tests.
- Rate limiter tests use monkeypatched `time.time()` to control rolling windows and cooldown expiry.
- Run with: `docker compose exec backend pytest` or `python -m pytest backend/tests/`
- Full suite parallel: `docker compose exec backend pytest -n auto`

## Code Quality

- Functions small (<50 lines), files focused (<800 lines).
- No deep nesting (>4 levels).
- Proper error handling, no hardcoded values.
- Readable, well-named identifiers.
- Always create new objects, never mutate shared state. Return new copies with changes applied.
