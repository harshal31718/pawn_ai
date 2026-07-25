# Git Workflow Rules

## Commit Format

Use conventional commits: `<type>(<scope>): <description>`

Types:
- `feat` — New feature
- `fix` — Bug fix
- `refactor` — Code restructuring without behavior change
- `docs` — Documentation only
- `test` — Adding or updating tests
- `chore` — Maintenance tasks
- `perf` — Performance improvement
- `ci` — CI/CD changes

Examples:
- `feat(chat): add streaming SSE support`
- `fix(registry): handle deprecated model endpoints`
- `refactor(routes): extract provider normalization`
- `test(chat): add streaming integration test`
- `docs: update build tracker for phase 2`

## Branch Workflow

- `main` — Production-ready code
- Feature branches: `feat/<name>`, `fix/<name>`
- Always create from `main`
- Delete branch after merge

## PR Workflow

1. Analyze full commit history
2. Draft comprehensive summary
3. Include test plan
4. Push with `-u` flag
5. Review all commits in the PR, not just the latest

## Pre-Commit Checklist

- All tests pass (`docker compose exec backend pytest` / `docker compose exec frontend npm run build`)
- No hardcoded secrets
- No provider isolation violations
- `workspace/current_state.md` updated
- `workspace/status/dev_log.md` has dated entry
- Commit message follows conventional format

## What NOT to Commit

- Files in `secrets/` (except `.gitkeep` and `*.example`)
- `.env` files
- Real API keys or tokens
- Docker secret files
- Build artifacts
- `node_modules/`
- `__pycache__/`
