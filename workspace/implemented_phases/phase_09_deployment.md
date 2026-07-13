# Plan: Production Deployment (Self-Hosted Postgres Migration + PAWN as a Second App on the Enma VM)

## Context

PAWN needs a `deployment.md` runbook to go live. **Decision reversed from an
earlier draft of this plan:** we are **not** creating a new Oracle Cloud
account. PAWN will be deployed as a **second, isolated app on the existing
Oracle Always-Free VM that already hosts Enma in production** (instance
`enma-production`, reserved public IP, `VM.Standard.A1.Flex`, ARM64, Ubuntu
24.04 LTS, 4 OCPU / 24 GB RAM). Reusing the account avoids Oracle's
dedup-detection risk entirely (no new card/phone/email needed) and the VM has
ample headroom (~20+ GB RAM, 70%+ CPU free as of 2026-07-03, estimated).

Everything **other than the Oracle account/VM itself** is still new and
isolated from Enma: new dedicated Gmail, new DuckDNS subdomain, new Google
Cloud OAuth client, own directory, own Nginx server block, own Docker Compose
project, own named volumes, own secrets. This mirrors the standard
"second app on the same box" pattern documented below — the coexistence
rules in this doc supersede and absorb the standalone `SECOND_APP_ON_SAME_VM.md`
file (that file has been folded in here and removed).

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

## What's already on the VM (do not disturb) — Enma's footprint

This is what's already running in production on the shared VM. PAWN's setup
must not touch, edit, or collide with any of it.

| Component | Enma's value |
|---|---|
| VM | `enma-production`, OCI Always Free, `VM.Standard.A1.Flex`, 4 OCPU / 24 GB RAM, ARM64, Ubuntu 24.04 LTS, reserved public IP (never release it) |
| Domain | `enmaquant.duckdns.org` — Google OAuth registered against this exact origin; never repoint this DNS record |
| Repo location | `/opt/enma`, owned by `ubuntu`, `main` branch |
| Nginx | Single system instance, **owns ports 80/443** exclusively. Config: `/etc/nginx/sites-available/enma` |
| Compose project | `/opt/enma/docker-compose.prod.yml` — services `redis`, `timescaledb`, `engine`, `server`. `client` is not containerized; Nginx serves a static build from `/opt/enma/client/dist` |
| Host-bound ports | Only `127.0.0.1:5000` (Node server). `engine`, `redis`, `timescaledb` publish no host ports at all |
| Named volumes | `enma_redis_data`, `enma_timescale_data`, `enma_engine_strategies` — never `docker compose down -v` this project |
| External services | MongoDB Atlas (M0, whitelisted to this VM's IP), Google OAuth (Enma's own client), Binance Testnet (outbound only) |
| `.env` | `/opt/enma/.env`, git-ignored — never read, log, copy, or reuse its values |
| Firewall (3 layers) | OCI Security List (22 restricted, 80/443 open to `0.0.0.0/0`) → host iptables (only 80/443/22 opened, insertion position can drift after OS upgrades) → Docker's own iptables chain (bypasses host INPUT — why only `127.0.0.1:5000` is published) |
| Idle-reclamation mitigation | Cron `keep_alive.sh` every 6h to dodge Oracle's Always-Free idle-reclamation check — do not remove |

## Hard rules for PAWN's deploy (never break these)

1. Never bind PAWN's containers to ports 80 or 443. Reach the internet via a
   **new** Nginx `server_name` block on PAWN's own subdomain — never claim
   Nginx's ports directly.
2. Never edit `/etc/nginx/sites-available/enma`. Create a new
   `/etc/nginx/sites-available/pawn` file instead.
3. Never put PAWN in `/opt/enma` or add its services to Enma's
   `docker-compose.prod.yml`. PAWN gets its own directory (`/opt/pawn`) and
   its own compose file/project.
4. Never publish a PAWN container port without a `127.0.0.1:` prefix unless
   deliberately opened at both the OCI Security List and host iptables layers
   first. Pick a free localhost port distinct from Enma's `5000` — PAWN's
   backend already targets `8001` (see D.2), so publish
   `127.0.0.1:8001:8001`.
5. Never touch `enma_redis_data`, `enma_timescale_data`, or
   `enma_engine_strategies` volumes, and never run
   `docker compose down -v` inside `/opt/enma`. PAWN's own volumes
   (`pawn_postgres_data`, etc.) must be uniquely named and confined to
   PAWN's compose project.
6. Never reuse Enma's MongoDB Atlas cluster, `.env` secrets, encryption key,
   or JWT secret, or its Google OAuth client. PAWN provisions everything
   fresh: new Gmail, new DuckDNS subdomain, new OAuth client, new
   `openssl rand`-generated secrets, its own Postgres+pgvector instance.
7. Never release or modify the VM's reserved public IP, and never repoint
   `enmaquant.duckdns.org`. PAWN's new DuckDNS subdomain resolves to the
   *same* IP (one VM, multiple domains, Nginx routes by `server_name`/SNI).
8. Don't restart/reconfigure the system `nginx` or `docker` services
   destructively. Always `sudo nginx -t` before every `reload`, and follow
   every PAWN-side Nginx change with a real HTTP check against
   `https://enmaquant.duckdns.org/api/v1/health` to confirm Enma is still
   served.
9. Because PAWN's workload (Postgres+pgvector, PostgREST, Kaggle image-gen
   rendezvous) can be resource-heavier than a small server, set Docker
   resource limits (`mem_limit`/`cpus` or `deploy.resources.limits`) on
   PAWN's containers so a runaway process can't starve Enma's trading
   engine — a CPU/OOM-starved Enma mid-session is worse than a slow PAWN.

## Decisions locked in (do not re-litigate)

1. **Reuse the existing Oracle Always-Free ARM64 VM (`enma-production`) and
   the existing Oracle account** — no new Oracle account, no new VM. PAWN is
   added as a second, fully isolated app per the hard rules above.
2. Everything PAWN-side on one VM — its own Nginx server block does TLS +
   static frontend + reverse proxy for PAWN. No Vercel/split-hosting.
3. New dedicated Gmail (distinct from Enma's) owns PAWN's DuckDNS domain +
   Google Cloud OAuth client.
4. Domain: `pawnai.duckdns.org` (new DuckDNS subdomain, distinct from
   `enmaquant.duckdns.org`), resolving to the same reserved IP.
5. Same-origin URL layout for PAWN — one domain for its frontend + API.
6. Repo is private → VM needs a read-only SSH deploy key for PAWN's repo
   (separate from whatever key, if any, Enma's `/opt/enma` checkout uses).
7. Branch hygiene: `dev` (testing, keeps all docs/agent files) / `main`
   (live, no docs). `main` is kept doc-free by a committed
   `scripts/promote-to-main.sh` (normal merge + strip docs), NOT by
   `.gitattributes merge=ours` (tested — broken for the modify/delete case).
   See D.5.
8. **Revised 2026-07-04 — no VM staging environment.** `dev` stays **local-only**
   (your machine, existing local Docker Compose stack) — it is never deployed
   to the shared VM. Only `main` is deployed, to `pawnai.duckdns.org`, as the
   single environment on the VM. Rationale: PAWN currently has no real user
   base (Google OAuth consent screen is in Testing mode with an explicit
   allowlist, not public), so the blast radius of a bad prod deploy is small,
   and the pre-deploy gate (D.6 — full pytest + build + live local Drive-less
   412 check) already substitutes for a dedicated staging environment. Deploy
   order is now: **verify locally (D.6) → promote `dev`→`main` via the script →
   deploy `main` to prod → verify on prod.** The one accepted tradeoff: local
   dev runs on x86, the VM is ARM64, so the first time any ARM-specific issue
   surfaces is during the real prod deploy, not a disposable staging box —
   acceptable at this stage given the small, allowlisted user base.
   OAuth/Drive/accounts: local dev and prod **share the same Google OAuth
   client** (both `http://localhost:8001/auth/callback` and
   `https://pawnai.duckdns.org/auth/callback` registered as redirect URIs on
   one client) and the same Google account(s) log into both — no separate
   throwaway account needed. Database/secrets stay **separate**: local dev
   keeps its own local Postgres container + its own `encryption_secret`/
   `jwt_secret`/`postgres_password`; prod gets its own freshly-generated set
   on the VM. This is deliberate, not an oversight — a shared DB would let
   bugs from local `dev`-branch testing corrupt real prod data, and a shared
   `encryption_secret` would let a compromised dev machine decrypt prod's
   BYOK keys. (If you'd rather share the same Postgres instance too, flag it —
   the safer default was chosen without an explicit answer from you.)
   **Known pre-existing gap, not blocking this deploy:** the Postgres RLS on
   `image_sessions`/`image_jobs` uses a permissive `pawn_anon` role, not
   scoped per-user — already documented elsewhere (Phase W) as "mandatory to
   fix before opening this app beyond the current allowlist," i.e. before
   flipping the OAuth consent screen from Testing to Production/public.
9. Database: self-hosted Postgres + pgvector, replacing Supabase, running as
   PAWN's own container(s) — never Enma's `timescaledb`. Kaggle kernel
   reaches it via a self-hosted **PostgREST** container, reverse proxied
   over HTTPS on PAWN's subdomain — mirrors the current Supabase
   REST/anon-key pattern.
10. PAWN's directory, compose project, volumes, ports, Nginx config, secrets,
    and OAuth client are all independent of Enma's, per the hard rules above.

## Steps

- [x] **D.1 — Kill hardcoded localhost values (CORS, OAuth redirect, CSP)**
  `backend/app/main.py` CORS → `CORS_ORIGINS` env var. `backend/app/routes/auth.py`
  `_FRONTEND_URL`/`_REDIRECT_URI` → `FRONTEND_URL`/`OAUTH_REDIRECT_URI` env
  vars (highest risk — must exactly match the Google OAuth client's
  registered redirect URI). `backend/app/middleware/security.py` CSP
  `connect-src` → same prod origin. All default to today's localhost values
  so dev is unaffected.

- [x] **D.2 — Fix frontend build-time API URL**
  Fix `frontend/.env.example` port (8000 → 8001, doc-only). Create
  `frontend/.env.production` (committed) with
  `VITE_API_URL=https://pawnai.duckdns.org`.

- [x] **D.3 — Migrate Supabase → self-hosted Postgres + pgvector**
  Add `postgres` (pgvector image, named volume `pawn_postgres_data`) service
  to `docker-compose.yml`. Replace `backend/app/db/supabase_client.py` with
  a **psycopg3-based sync client** (connection pool via `psycopg_pool`) —
  chosen over asyncpg because every existing Supabase call site today is a
  synchronous function invoked through `run_in_threadpool` (~25 call sites
  across `routes/chat.py`, `conversations.py`, `upload.py`, `generate.py`,
  `crypto.py`, `memory/summarize.py`); psycopg3 preserves that exact
  sync-function-behind-run_in_threadpool shape everywhere, so only the 7
  files below change instead of a 15–20 file async ripple. Rewrite
  `.table()/.rpc()` calls in `auth.py`, `key_store.py`, `drive_factory.py`,
  `memory/index.py`, `memory/retrieve.py`, and `core/image_session.py`'s
  session/job CRUD (its Kaggle-payload injection of `supabase_url`/`anon_key`
  stays as-is until D.4 swaps it to PostgREST) as direct parameterized SQL
  (`%s` placeholders — never string-format SQL). Port `supabase/schema.sql`
  (renamed to `postgres/schema.sql` once done — the old name stopped making
  sense) to plain Postgres (add `create extension if not exists pgcrypto;` — needed
  for `gen_random_uuid()`, missing today). Drop `supabase` from
  `requirements.txt`, add `psycopg[binary,pool]`. Drop `supabase_url`/
  `supabase_service_key`/`supabase_anon_key` secrets, add
  `postgres_password`/`postgres_dsn`. Because dropping `supabase_url`/
  `supabase_anon_key` breaks `image_session.py`'s Kaggle-payload injection,
  D.3 and D.4 are implemented together as one coherent change (tracked as
  separate checklist items, committed together) — matches the plan's own
  pause point (after D.3+D.4, before D.7/D.8).

- [x] **D.4 — Migrate Kaggle rendezvous → self-hosted PostgREST**
  Add `postgrest` service (internal only, no host port) pointed at the new
  Postgres. Rewrite RLS policies on `image_sessions`/`image_jobs` under
  PostgREST's role-switching model (`pawn_anon` role replacing Supabase's
  `anon`). Update `backend/app/core/image_session.py`'s `start_session()`
  Kaggle-payload injection (currently `supabase_url`/`anon_key`) to inject
  the new `postgrest_url`/`postgrest_anon_key` instead — this is the only
  part of `image_session.py` D.4 touches; its own session/job CRUD already
  moved to direct psycopg SQL in D.3. New `postgrest_jwt_secret` secret
  (HS256, mints the anon role's JWT for PostgREST — Supabase's newer
  `sb_publishable_*` keys don't apply here since this is self-hosted).

- [x] **D.5 — Clean-`main` promotion mechanism (`scripts/promote-to-main.sh`)**
  **Superseded mechanism:** the original `.gitattributes merge=ours` approach
  was tested and **does not work** for this goal — once docs are removed from
  `main`, `merge=ours` is never consulted for the resulting modify/delete, so
  every `dev`→`main` merge that touched a tracked doc conflicts (and
  `workspace/` changes almost every step). Dropped entirely; no `.gitattributes`.
  **Actual mechanism:** committed `scripts/promote-to-main.sh` does a *normal*
  merge `dev`→`main` (which advances the merge base, so code merges cleanly
  every round) then unconditionally strips the dev-only doc paths (`.claude/`,
  `workspace/`, any `CLAUDE.md`/`AGENTS.md`; keeps `README.md`) and commits.
  Proven clean and repeatable against a real repo clone (39 doc paths → 0,
  123 code files preserved). **Constraint:** `dev`→`main` must ALWAYS go through
  this script — a plain `git merge dev` re-adds the docs. The first real run
  (which strips the current docs off `main`) happens at deploy time in D.8,
  not as a standalone step.

- [x] **D.6 — Pre-deploy test gate**
  `pytest` full suite green (152 passed), `npm run build` clean, all compose
  configs valid, and the Drive-mandatory 412-when-unavailable path
  live-verified against the running local stack. The Drive-**linked** happy
  path (needs a real Google token) is deferred to D.8's live prod verify —
  there is no separate staging environment to run it against first (see the
  no-staging decision above).

- [x] **D.7 — Write `deployment.md` (VM runbook, second-app-on-Enma-VM style)**
  ~~Originally scoped for two environments (staging + prod); simplified~~
  **Revised 2026-07-04 — single environment (prod only).** Covers `/opt/pawn`
  on the shared VM. Prerequisites checklist (dedicated Gmail, DuckDNS subdomain
  `pawnai.duckdns.org`, SSH access to the *existing* `enma-production` VM —
  **no new Oracle account, no new instance, no Security List changes needed**
  since 80/443 are already open and PAWN's backend stays loopback-only) →
  confirm VM headroom and that Enma is currently healthy (`docker compose -f
  /opt/enma/docker-compose.prod.yml ps`, `curl
  https://enmaquant.duckdns.org/api/v1/health`) → external services (Google
  Cloud OAuth client + Drive API for PAWN — same client used for local dev,
  with both `http://localhost:8001/auth/callback` and
  `https://pawnai.duckdns.org/auth/callback` registered as redirect URIs;
  `pawnai.duckdns.org` A-record pointed at the *same* reserved IP) → per-app
  setup on the shared VM (`sudo mkdir -p /opt/pawn`, clone PAWN's repo there
  with its own deploy key, own `docker-compose.prod.yml` with an explicit
  `name: pawn` project name) → production secrets population for PAWN
  (file-based Docker secrets, freshly generated and **distinct from local
  dev's** — never copied from Enma's `.env` or from local dev's secrets) →
  frontend static build → new Nginx server block at
  `/etc/nginx/sites-available/pawn` (`server_name pawnai.duckdns.org`,
  `proxy_pass http://127.0.0.1:8001`), symlink into `sites-enabled`,
  `sudo nginx -t` before every reload → TLS via
  `sudo certbot --nginx -d pawnai.duckdns.org` (additive, doesn't
  touch Enma's cert) → `docker-compose.prod.yml` for PAWN (backend bound to
  `127.0.0.1:8001` only, `postgres` named volume `pawn_postgres_data`,
  `postgrest` internal-only, no frontend service, resource limits per hard
  rule 9) → deploy & verify checklist (PAWN's own health check, **then**
  re-verify Enma's health endpoint and `docker compose ps` per hard rule 8)
  → release/update workflow (`git pull` + rebuild inside `/opt/pawn` only)
  → data safety notes (PAWN's named Postgres volume backup, never `down -v`
  on `/opt/pawn`, and never touch Enma's volumes) → firewall/exposure summary
  table. **`deployment.md` rewritten prod-only 2026-07-04** (the staging
  section is fully removed, not just noted as stale — the follow-up edit pass
  is done).

- [ ] **D.8 — First live deploy + full verify checklist (prod only, no staging)**
  Execute `deployment.md` end to end on the shared VM, single environment:
  1. **Promote** `dev`→`main` via `scripts/promote-to-main.sh` (first run also
     strips docs off `main`); review, push `main`.
  2. **Prod** (`/opt/pawn`, `main` branch, `pawnai.duckdns.org`) — full verify:
     health endpoint, HTTPS with clean CSP console, full Google OAuth
     round-trip (this is also the first live check of the Drive-linked happy
     path deferred from D.6), BYOK LLM SSE round-trip, one Kaggle image-gen
     job exercising the PostgREST rendezvous path (highest-risk item).
  After each shared-VM action and at the end, confirm Enma is untouched: its
  health endpoint, `docker compose ps` status, and that `enmaquant.duckdns.org`
  still resolves and serves correctly.

## Critical files

- `backend/app/main.py`, `backend/app/routes/auth.py`,
  `backend/app/middleware/security.py` (D.1)
- `backend/app/db/supabase_client.py` → new Postgres client module (D.3)
- `backend/app/core/key_store.py`, `drive_factory.py`, `memory/index.py`,
  `memory/retrieve.py`, `core/image_session.py` (D.3, D.4)
- `supabase/schema.sql` → adapted for plain Postgres + PostgREST roles, then
  renamed to `postgres/schema.sql` (D.3, D.4)
- `backend/app/config.py`, `backend/requirements.txt` (D.3)
- `docker-compose.yml` (local dev), `docker-compose.prod.yml` (single prod
  deploy, no staging variant) (D.3, D.4, D.7)
- `frontend/.env.example`, `frontend/.env.production` (D.2)
- New `scripts/promote-to-main.sh` (D.5) — replaces the abandoned `.gitattributes`
- New `deployment.md` at repo root (D.7)

## Quick reference — what's whose (on the shared VM)

| Thing | Enma's value | PAWN uses |
|---|---|---|
| Oracle account/VM | `enma-production` | **same** — no new account/VM |
| Directory | `/opt/enma` | `/opt/pawn` |
| Domain | `enmaquant.duckdns.org` | `pawnai.duckdns.org`, same reserved IP |
| Nginx config file | `/etc/nginx/sites-available/enma` | `/etc/nginx/sites-available/pawn` |
| Localhost port | `127.0.0.1:5000` | `127.0.0.1:8001` |
| Compose project | `docker-compose.prod.yml` in `/opt/enma` | its own compose file, own directory, own project name |
| Docker volumes | `enma_redis_data`, `enma_timescale_data`, `enma_engine_strategies` | `pawn_postgres_data` + any others, uniquely named |
| Database | MongoDB Atlas (`enma_trading`/`enma_candles`) | self-hosted Postgres+pgvector, own container |
| OAuth client | Enma's Google Cloud project/client | PAWN's own new client |
| Secrets | `/opt/enma/.env` | Docker secret files under `/opt/pawn`, freshly generated |

The "PAWN uses" column above is the *only* deployed environment (prod). `dev`
is never deployed to the VM — it stays local-only on your own machine, using
its own local Postgres/secrets, and shares the Google OAuth client + account
with prod (see the revised decision 8 above) rather than needing an isolated
VM stack of its own.

## Working agreement

Same as the rest of the project: implement steps sequentially, tests pass
before marking `[x]`, update `workspace/current_state.md` and
`workspace/status/build_tracker.md` after every step. Given the size of this
plan (a real DB migration, not a small feature), pause for confirmation
between D.3/D.4 (the migration) and D.7/D.8 (the actual live deploy) rather
than running straight through. Because D.7/D.8 now touch a VM that already
runs a live trading app, treat every VM-side command as reversible-with-care:
always confirm Enma's health before *and* after any shared-VM action
(Nginx reload, certbot run, firewall check).
