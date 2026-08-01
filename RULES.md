# Rules

## Must Always

- Delegate to specialized agents for domain tasks.
- All LLM calls go through `backend/app/core/normalize.py` only — never call providers directly.
- Secrets come from `/run/secrets/*` via `app/config.py` — never hardcoded, never `.env`.
- Write tests before implementation and verify critical paths.
- Validate inputs and keep security checks intact.
- Prefer immutable updates over mutating shared state.
- Follow established repository patterns before inventing new ones.
- Update `workspace/current_state.md` and `workspace/status/dev_log.md` after every step.
- Keep contributions focused, reviewable, and well-described.
- Use `app/events.py` builder functions for SSE — never raw `f"data: {x}\n\n"` in routes.

## Must Never

- Include sensitive data such as API keys, tokens, secrets, or absolute/system file paths in output.
- Call `llm_core.py` directly from routes — always go through `normalize.py`.
- Use `os.getenv()` for raw key names — secrets come from `read_secret()` only.
- Submit untested changes.
- Bypass security checks or validation hooks.
- Duplicate existing functionality without a clear reason.
- Ship code without checking the relevant test suite.
- Commit files in `secrets/` (except `.gitkeep` and `*.example`).
- Use `allow_origins=["*"]` in CORS configuration.
- Remove `SecurityHeadersMiddleware` from the middleware stack.

## Agent Format

- Agents live in `.claude/agents/*.md`.
- Each file includes YAML frontmatter with `name`, `description`, `tools`, and `model`.
- File names are lowercase with hyphens and must match the agent name.
- Descriptions must clearly communicate when the agent should be invoked.

## Skill Format

- Skills live in `.claude/skills/<name>/SKILL.md`.
- Each skill includes YAML frontmatter with `name`, `description`.
- Skill bodies should include practical guidance, tested examples, and clear "When to Use" sections.

## Hook Format

- Hooks use matcher-driven JSON registration and shell or PowerShell entrypoints.
- Matchers should be specific instead of broad catch-alls.
- Exit `1` only when blocking behavior is intentional; otherwise exit `0`.
- Error and info messages should be actionable.

## Commit Style

- Use conventional commits such as `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`.
- Keep changes modular and explain user-facing impact in the PR summary.
