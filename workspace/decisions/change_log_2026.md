# PAWN — Decision & Action Log, 2026-07 to 2026-11

**Audience: AI agents.** Why the system looks the way it does today, written as
decision -> action -> why -> what to remember. Newest first. This is the "reasoning"
companion to `workspace/CODEBASE_MAP.md` (what exists) and `workspace/current_state.md`
(where things stand). Day-by-day history stays in `status/dev_log.md`; do not duplicate it here.

Last reconciled: 2026-11-01.

---

## Infrastructure and deployment

### 2026-10-30 — Prod DB: Supabase dropped, local Postgres container restored
- **Trigger:** `/auth/callback` returned `Token exchange failed`, then 500. Two causes:
  a one-off `SSLEOFError` VM -> `oauth2.googleapis.com` (burned the single-use code, so retries
  gave `invalid_grant`), and the Supabase project the prod DSNs pointed at no longer existed
  (`FATAL: (ENOTFOUND) tenant/user ... not found`).
- **Decision:** run Postgres locally on the e2-micro instead of any hosted DB.
- **Action:** `docker-compose.prod.yml` gained a `postgres` service (`pgvector/pgvector:pg16`,
  `shared_buffers=32MB`, `max_connections=30`, `mem_limit: 200m`, ~85 MB real use).
  New secrets `postgres_password`, `postgrest_anon_password`; DSNs now point at `postgres:5432`.
  Added `scripts/backup-db.sh` + nightly cron (03:30 UTC, keep 7) on the VM.
  Shipped on `main` as `59622bc` + `4b97c2a`; synced into `dev` as `32d851c`.
- **Why local works now:** the original reason for Supabase was "Postgres will not fit in 1 GB".
  Measured, it does (backend 500m + postgres 200m + postgrest 128m, swapfile as burst buffer).
- **Consequences:** prod DB was recreated EMPTY (users re-register, re-add keys, re-link Drive;
  user content was never in the DB, it is in each user's Drive). Dumps die with the VM, so copy
  them off occasionally. Init scripts (`schema.sql`, `init_pawn_anon.sh`) run only on an empty
  volume; later schema changes are applied by hand from `postgres/migrations/`.
- **Rule:** never `docker compose down -v` on the VM (deletes `pawn_postgres_data`).
- **Sync mechanism:** `main` has docs stripped, so a real merge main -> dev would delete docs
  on dev. The three infra files were synced with `git checkout main -- <files>` instead.

### 2026-08-30 — Oracle account terminated; fresh deploy on GCP e2-micro + Supabase
- **Trigger:** Oracle terminated the account and the `pawn` VM (`144.24.119.184`), involuntary and
  unrecoverable. No user data was lost (Drive holds all user content); Postgres contents
  (accounts, BYOK keys, embeddings) were lost with the VM.
- **Decision:** GCP `e2-micro` (Always Free: 1 shared vCPU, 1 GB RAM, x86_64, `us-central1`,
  Standard PD, static IP `136.114.65.94`). Chosen for the longest-unchanged free-tier track record
  after Oracle proved free tiers can be revoked. Same-day *fresh deploy*, not a data migration.
- **Action:** project `pawn-501409`, user `pawndeploy`, DuckDNS `pawnai` repointed, system Nginx +
  certbot, 1 GB swapfile, $1 budget alert. Postgres was first put on Supabase (assumed too big for 1 GB).
- **Fixes found live (all in `deployment.md`):**
  1. Compose caps retuned for the 1 GB box (`backend` 500m/0.5 cpu, `postgrest` 128m/0.1 cpu).
  2. `postgrest_db_uri` secret: this Compose version silently ignores `secrets.mode/uid/gid`.
     Compose bind-mounts the host file, so it keeps host ownership. postgrest runs as UID 1000, so
     the fix is host-side `chown 1000:1000` + `chmod 400`. `chmod 644` was deliberately avoided
     (exposes a live DB credential to every local user).
  3. **Google Drive API must be enabled on the GCP project.** If not, OAuth succeeds and tokens are
     stored, but every Drive call 403s `accessNotConfigured`, surfacing as "Connect your Google
     Drive in Providers" forever. Check this FIRST for any Drive symptom.
  4. GCP Console "SSH Keys" metadata is unreliable; use the browser SSH once to create
     `pawndeploy` and install the key by hand.
  5. Drive-required error message corrected to point at Providers (`fix(auth)` `1386578`).
- **Accepted risk (documented in `deployment.md` section 8):** OAuth consent screen is *Published*
  while `/pgrst/` is publicly reachable. The `pawn_anon` role is scoped by per-session-token RLS
  (see 2026-07-04 below), but scoped per-session JWT is still deferred.
- **Not recreated:** the local-dev PostgREST SSH tunnel to prod (`pgrst-tunnel` / `keys-tunnel` in
  `docker-compose.yml` still hardcode the dead Oracle IP). Local warm-session testing needs it redone.

### 2026-07-23 — PAWN 2.0 release deployed (two deploys + Nginx hotfix)
- `main` `22695be` -> `2e75d14` -> `6fe867c` -> `4e93afb`. Migrations applied to prod first
  (`users` password columns, `endpoint_usage`, `pool_api_keys`), `pg_dump` taken (151 MB), then
  `scripts/promote-to-main.sh`, VM `git pull`, frontend rebuild, `up -d --build`.
- **Nginx lesson:** the VM's hand-maintained Nginx only proxies an *allowlist* of path prefixes
  to `:8001`. New routers (`account`, `admin`, `dashboard`, `memory`, latent `projects`) were missing,
  so their API calls fell through to the SPA `try_files` (GET -> HTML, PUT -> 405).
  `/chat` and `/projects` collide with SPA page routes, so they get method/auth-aware blocks.
  **Rule: the Nginx prefix regex in `deployment.md` section 6.4 must stay in sync with
  `backend/app/routes/*` router prefixes.**
- **Config drift caught:** VM `.env.prod` lacked `PAWN_ENV` (predates Phase E.1). Isolation keys off
  `== "dev"`, so it worked by accident; set `PAWN_ENV=prod` explicitly.
- **Embeddings bug:** `memory/embed.py` was BYOK-only, breaking memory for keyless/pool users.
  Now BYOK-first with pool fallback, same precedence as chat.
- Chat-Gemini failure diagnosed as NOT quota (0 usage recorded): the "Generative Language API"
  needs enabling on the Google key's GCP project.

### 2026-07-17 / 2026-07-04 / 2026-07-05 — First production deploys (Oracle era, historical)
- First live deploy was on a temporary paid bridge VM (`pawn-temp`) while retrying for the free ARM
  instance; data-preserving move to the free `pawn` instance on 2026-07-05.
- Bugs that shaped current config: host iptables only allowed SSH (Oracle-specific, gone on GCP);
  `/pgrst/` Nginx `client_max_body_size` default 1 MB 413'd base64 image write-backs (now `20m`);
  warm-session startup timeout 300 s was too short (now `IMAGE_SESSION_STARTUP_TIMEOUT_SECONDS = 900`);
  CSP `img-src` lacked `data:` so Image Lab thumbnails were blocked (needed in BOTH backend
  `SecurityHeadersMiddleware` and the static-site Nginx block).
- `scripts/promote-to-main.sh` was dying before its final commit (a `while read` over a pipe exits 1;
  under `set -e`). Fixed.
- **2026-07-04 `pawn_anon` RLS:** `/pgrst/` is public and unauthenticated. Warm-session notebooks now
  send `X-Session-Token` on every PostgREST call; RLS policies in `postgres/schema.sql` require it to
  match before SELECT/UPDATE. Wrong/no token returns `[]`.

---

## Product and architecture

### 2026-07-21..23 — PAWN 2.0: operator pool, admin, fair-share quota, provider registry
- **Decision:** keep BYOK as the primary model, add an operator "pool" of shared provider keys as a
  fallback for keyless users, with fair-share quota so one user cannot drain it.
- **Action:** `pool_api_keys` table (AES-GCM, admin-edited via `routes/admin.py`, 60 s cache),
  `core/quota_share.py` (port of OmniRoute's idea, no shared code; blocks at pool-wide limit and
  tightens to per-user fair share past `saturation_pct`, default 80), `endpoint_usage` table for
  persisted day/month windows (circuit breaker degrades to memory-only after 3 failures),
  `config.read_pool_key` = DB first, `pool_<provider>_api_key` Docker secret as bootstrap fallback.
  Admin = single hardcoded `ADMIN_EMAIL`.
- **Reversal worth remembering:** `key_source: either` was pool-first, now **BYOK-first, pool
  fallback**, so a user's own key is always used when present.
- **`providers.json`** (`backend/data/registry/`, 15 entries) is now the single source of truth for
  provider ids/aliases/types, replacing ~6 hardcoded lists. The Model schema in
  `workspace/schemas/model_schema.md` is documented but NOT implemented.
- **Dashboard rows** carry independent `available_via_byok` / `available_via_pool`, so the UI shows
  "Both" instead of hiding the pool when a BYOK key also exists.
- **Providers page** rebuilt as 3 tabs (Models, Providers/BYOK, Admin). `position: sticky` caused two
  rounds of layout bugs; final design is a static header area with only the rows scrolling in a
  `min-h-0` flex child. Old `/admin` route and `AdminPage.tsx` deleted.
- **Test isolation gap (recurring):** resolver/dashboard read pool keys and usage from the real dev
  Postgres. Mitigated with autouse `stub_pool_keys` in `conftest.py`; a real per-test DB isolation
  pass is still owed.

### 2026-07-23 — Login change
- Split Sign In / Sign Up, added email+password (Argon2id, `core/password_utils.py`), login rate
  limiter (8 failures per `(ip,email)` per 15 min), `PUT /account/password` with NO current-password
  check by design (doubles as "forgot"). Pre-existing Google accounts have no `password_hash`.

### 2026-07-13/14 — Phase A (agent) and Phase M (memory scoping)
- **Agent:** the old 5-node ReAct-JSON graph was replaced by `classify -> direct_answer | plan ->
  execute -> verify` with native OpenAI-style tool calling, three preset subagents (depth 1),
  and a mandatory research-tier closing synthesis on heavy turns. Router heuristics decide
  light/heavy and whether tools are needed.
- **Memory:** per-chat and per-project isolated RAG. Folder placement in Drive is the sole source of
  truth for scope; Postgres `memory_chunks` is a rebuildable derived index (chunks go to
  `rag_chunks.jsonl` on Drive first). Embedding model swapped from the dead `text-embedding-004` to
  `gemini-embedding-2` at 768 dims.

### 2026-07-03 — Self-hosted Postgres + PostgREST replace Supabase (first time), Drive mandatory
- **Decision:** drop the Supabase SDK; use psycopg3 (sync, behind `run_in_threadpool`, per-call
  connect) + self-hosted PostgREST as the Kaggle rendezvous. `supabase/` dir renamed `postgres/`.
- **Decision:** Google Drive is the ONLY storage for user data. All local-filesystem fallbacks
  removed; no Drive link -> HTTP 412 `not_configured`. Stateless chat (no conversation, no doc)
  still works without Drive. The client-side passphrase gate was removed; WebCrypto code under
  `frontend/src/crypto/` is foundation-only and unwired.

### 2026-06 — Founding decisions that still hold
- All providers speak the OpenAI-compatible wire format; no provider SDKs.
- Routes -> `normalize.py` -> `llm_core.py`. Registry is JSON data, rows are deactivated, never deleted.
- Optimistic UI: client-generated conversation UUIDs, persisted sync queue, frontend-only draft
  "New Chat".
- Kaggle for GPU (SDXL, FLUX.1-schnell) with warm sessions rendezvousing through PostgREST; cold
  jobs are durable rows polled by the client; double-submit prevented server-side per `(user, model)`.

---

## Documentation and workflow

### 2026-11-01 — Docs reconciliation
- Split docs by audience (see `workspace/README.md`). Deleted: `RULES.md` (merged into
  `.claude/AGENTS.md`), `pawn_context.md` (merged here and into CLAUDE.md), `workspace/api_reference.md`
  (outdated; CODEBASE_MAP section 6 replaces it), `decisions/claude_setup_guide.md` (one-time scaffold
  guide), `decisions/project_overview.md` (folded into `OVERVIEW.md`), duplicated `.gemini/skills/*`.
- The "main has hotfixes not in dev" warning is **closed**: deploy files were synced on 2026-10-30.
  The only dev-vs-main code gap is `81e52ad` (kaggle 401 vs 403 messages), not yet promoted.
- `workspace/stable_commits.md` is intentionally untouched (only updated on explicit request) and
  currently lags: `dev` row predates the 10-30 sync.

### Dev/prod promotion flow (unchanged, easy to get wrong)
`dev` is the working branch with all docs. `main` is deploy-only. ALWAYS promote with
`scripts/promote-to-main.sh` (merges, then strips `.claude/`, `workspace/`, `CLAUDE.md`, `AGENTS.md`);
a plain `git merge dev` drags docs onto `main`. Infra-only changes (compose, `deployment.md`) may be
committed straight to `main` and then synced to `dev` with `git checkout main -- <files>`.
