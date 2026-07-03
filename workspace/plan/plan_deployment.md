# Plan: Production Deployment (Self-Hosted Postgres Migration + Oracle VPS)

## Context

PAWN needs a `deployment.md` runbook to go live on a second Oracle Cloud
Always-Free ARM VM — a **separate Oracle account** from the existing "Enma"
project deployment (different card, phone, email), since Oracle's dedup
detection keys off card+phone and reuse risks both accounts being suspended.

Scope grew during planning: the user decided to **drop Supabase entirely**
in favor of a self-hosted Postgres+pgvector database on the same VPS. This is
a real code migration (7 backend files use `supabase-py`), not just infra
config, and is folded into this same plan alongside the VPS deployment steps.

Full architecture decisions and rationale are captured in the approved plan
at the session's plan file (superseded by this workspace copy as the durable
record). Key facts verified against the codebase (commit `02f1921` on `dev`):

- Hardcoded `localhost` values that must go: `backend/app/main.py` (CORS),
  `backend/app/routes/auth.py:44-45` (`_FRONTEND_URL`, `_REDIRECT_URI`),
  `backend/app/middleware/security.py:15` (CSP `connect-src`).
- All API routes are root-level, no `/api` prefix: `/health`, `/auth/*`,
  `/chat`, `/generate*`, `/conversations*`, `/registry/models`, `/keys*`, `/upload`.
- Supabase touchpoints (7 files): `backend/app/db/supabase_client.py`,
  `backend/app/routes/auth.py`, `backend/app/core/key_store.py`,
  `backend/app/core/drive_factory.py`, `backend/app/memory/index.py`,
  `backend/app/memory/retrieve.py`, `backend/app/core/image_session.py`.
- Auth is 100% custom (Google OAuth + own JWT) — Supabase was pure Postgres,
  never Supabase Auth. Migration doesn't touch identity.
- `secrets/` has 13 app-read secrets + one stray unread file
  `secrets/supabase_project_password` (dropped along with Supabase).

## Decisions locked in (do not re-litigate)

1. Single Oracle Always-Free ARM64 VM (`VM.Standard.A1.Flex`), separate
   account from Enma.
2. Everything on one VM — Nginx does TLS + static frontend + reverse proxy.
   No Vercel/split-hosting.
3. New dedicated Gmail owns DuckDNS domain + Google Cloud OAuth client.
4. Domain: DuckDNS subdomain, placeholder `<pawn-domain>.duckdns.org`.
5. Same-origin URL layout — one domain for frontend + API.
6. Repo is private → VPS needs a read-only SSH deploy key.
7. Branch hygiene: adopt Enma's `dev`/`main` split via `.gitattributes`
   `merge=ours` for `.claude/`, `workspace/`, `CLAUDE.md`.
8. Database: self-hosted Postgres + pgvector, replacing Supabase. Kaggle
   kernel reaches it via a self-hosted **PostgREST** container, reverse
   proxied over HTTPS — mirrors the current Supabase REST/anon-key pattern.

## Steps

- [ ] **D.1 — Kill hardcoded localhost values (CORS, OAuth redirect, CSP)**
  `backend/app/main.py` CORS → `CORS_ORIGINS` env var. `backend/app/routes/auth.py`
  `_FRONTEND_URL`/`_REDIRECT_URI` → `FRONTEND_URL`/`OAUTH_REDIRECT_URI` env
  vars (highest risk — must exactly match the Google OAuth client's
  registered redirect URI). `backend/app/middleware/security.py` CSP
  `connect-src` → same prod origin. All default to today's localhost values
  so dev is unaffected.

- [ ] **D.2 — Fix frontend build-time API URL**
  Fix `frontend/.env.example` port (8000 → 8001, doc-only). Create
  `frontend/.env.production` (committed) with
  `VITE_API_URL=https://<pawn-domain>.duckdns.org`.

- [ ] **D.3 — Migrate Supabase → self-hosted Postgres + pgvector**
  Add `postgres` (pgvector image, named volume) service to `docker-compose.yml`.
  Replace `backend/app/db/supabase_client.py` with an asyncpg-based client.
  Rewrite `.table()/.rpc()` calls in `auth.py`, `key_store.py`,
  `drive_factory.py`, `memory/index.py`, `memory/retrieve.py` as direct
  parameterized SQL. Port `supabase/schema.sql` to plain Postgres
  (`gen_random_uuid()`/`pgcrypto` check). Drop `supabase` from
  `requirements.txt`, add `asyncpg`. Drop `supabase_url`/`supabase_service_key`/
  `supabase_anon_key` secrets, add `postgres_password`/`postgres_dsn`.

- [ ] **D.4 — Migrate Kaggle rendezvous → self-hosted PostgREST**
  Add `postgrest` service (internal only, no host port) pointed at the new
  Postgres. Rewrite RLS policies on `image_sessions`/`image_jobs` under
  PostgREST's role-switching model (`pawn_anon` role replacing Supabase's
  `anon`). Update `backend/app/core/image_session.py` to call the new
  PostgREST URL instead of Supabase's, with a `postgrest_jwt_secret`.

- [ ] **D.5 — `.gitattributes` + branch hygiene**
  Create `.gitattributes` marking `.claude/**`, `workspace/**`, `CLAUDE.md`,
  `**/CLAUDE.md` as `merge=ours`. One-time `git config merge.ours.driver true`
  on the release machine. Dry-run `dev`→`main` merge to confirm.

- [ ] **D.6 — Pre-deploy test gate**
  `pytest` full suite green (Supabase-mocking tests rewritten for Postgres),
  `npm run build` clean. Local dry run: bring up `postgres`+`postgrest`+`backend`
  via dev compose, confirm memory retrieval + BYOK key storage work
  end-to-end before touching prod.

- [ ] **D.7 — Write `deployment.md` (VPS runbook)**
  Prerequisites checklist (Gmail, DuckDNS, second Oracle account, reserved
  IP) → Oracle VPS setup (instance, Security List, host-iptables gotcha) →
  external services (Google Cloud OAuth client + Drive API, DuckDNS A-record)
  → VPS base setup (Docker, Nginx, certbot, private repo deploy key) →
  production secrets population (file-based Docker secrets, final list
  post-Supabase-removal) → frontend static build → Nginx config + TLS →
  `docker-compose.prod.yml` (backend loopback-only, postgres named volume,
  postgrest internal-only, no frontend service) → deploy & verify checklist
  → release/update workflow → data safety notes (named Postgres volume backup,
  never `down -v`) → firewall/exposure summary table.

- [ ] **D.8 — First live deploy + full verify checklist**
  Execute `deployment.md` end to end on the real VPS. Health endpoint, HTTPS
  load with clean CSP console, full Google OAuth round-trip, BYOK LLM SSE
  round-trip, one Kaggle image-gen job exercising the new PostgREST
  rendezvous path (highest-risk item — newest, least-proven part of the
  migration).

## Critical files

- `backend/app/main.py`, `backend/app/routes/auth.py`,
  `backend/app/middleware/security.py` (D.1)
- `backend/app/db/supabase_client.py` → new Postgres client module (D.3)
- `backend/app/core/key_store.py`, `drive_factory.py`, `memory/index.py`,
  `memory/retrieve.py`, `core/image_session.py` (D.3, D.4)
- `supabase/schema.sql` → adapted for plain Postgres + PostgREST roles (D.3, D.4)
- `backend/app/config.py`, `backend/requirements.txt` (D.3)
- `docker-compose.yml`, new `docker-compose.prod.yml` (D.3, D.4, D.7)
- `frontend/.env.example`, new `frontend/.env.production` (D.2)
- New `.gitattributes` (D.5)
- New `deployment.md` at repo root (D.7)

## Working agreement

Same as the rest of the project: implement steps sequentially, tests pass
before marking `[x]`, update `workspace/current_state.md` and
`workspace/status/build_tracker.md` after every step. Given the size of this
plan (a real DB migration, not a small feature), pause for confirmation
between D.3/D.4 (the migration) and D.7/D.8 (the actual live deploy) rather
than running straight through.
