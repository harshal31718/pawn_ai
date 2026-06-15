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
