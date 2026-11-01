# PAWN — The Current Picture (for you)

**Audience: you, the owner.** Only what is true today. No history, no old designs.
Last reconciled: 2026-11-01. For the *why* behind things, see `workspace/decisions/change_log_2026.md`;
for the code-level map, `workspace/CODEBASE_MAP.md` (both written for AI agents).

---

## What PAWN is

One chat interface in front of 11 free-tier AI providers (47 endpoints). You bring your own API keys; if
you have none for a provider, an optional shared "pool" of keys you (the admin) fund can fill in, with a
fair-share limit so nobody drains it. When one provider rate-limits, PAWN moves to another host or model
before the first word is produced, so the chat does not die. It also has scoped memory (per chat, per
project), a tool-using agent (web search, URL fetch, calculator, memory search, image generation), and an
Image Lab that runs SDXL / FLUX on each user's own free Kaggle GPU.

Your data stays with each user: chats, summaries, uploads and memory source files live in **their own
Google Drive**. PAWN's database only holds accounts, encrypted keys and tokens, search embeddings, usage
counters and image-job state.

## Where it runs

| | |
|---|---|
| Address | `https://pawnai.duckdns.org` |
| Server | One Google Cloud `e2-micro` VM (free tier, 1 GB RAM), IP `136.114.65.94`, user `pawndeploy`, code in `/opt/pawn` |
| What runs on it | Nginx (HTTPS, serves the built website, forwards API calls) + three Docker containers: `backend`, `postgres`, `postgrest` |
| Database | Postgres **on the same VM** in a container (~85 MB RAM). Supabase is gone for good |
| Backups | Nightly dump at 03:30 UTC, last 7 kept in `/opt/pawn/backups`. They are on the same disk as the database, so copy them off the VM sometimes |
| Local development | `docker compose up` on your machine (backend :8001, site :5174). It never touches the VM |

How we got here, briefly: Oracle shut down the old server on 2026-08-30, so PAWN was rebuilt the same day
on Google Cloud. The database first lived on Supabase; that project disappeared on 2026-10-30 and broke
login, so Postgres was moved onto the VM. The production database was recreated empty then: users re-signed
in and re-added their keys; no chat data was lost because chats are in Drive.

## How your code gets to production

1. Work and test on `dev` (all the docs live here).
2. `scripts/promote-to-main.sh` merges `dev` into `main` and strips the docs and AI config from `main`.
   Never merge `dev` into `main` by hand, or the docs leak onto `main`.
3. `git push origin main`.
4. On the VM: `git pull origin main`, rebuild the frontend if it changed, then
   `docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build`.
5. Check `https://pawnai.duckdns.org/health`.

Full step-by-step, Nginx config and secrets: `deployment.md`.

**Things that will bite you** (all learned the hard way):
- Never run `docker compose down -v` on the VM. It deletes the database.
- If you add a new backend route prefix, also add it to the Nginx list on the VM, or the website will
  swallow its calls (`deployment.md` section 6.4).
- Database setup scripts only run on an empty database. Later schema changes are applied by hand from
  `postgres/migrations/`.
- If Drive linking "works" but the app keeps saying "Connect your Google Drive": the Google Drive API is
  probably not enabled on the Google Cloud project.
- 1 GB of RAM is tight. If containers restart often, move to a bigger VM (`e2-small`).

## State of the code

- Branches: `main` is what is deployed; `dev` equals `main` plus docs plus **one small unreleased fix**
  (clearer Kaggle error messages for 401 vs 403). Nothing is half-built.
- Tests: 801 backend tests passed at the last full run (2026-07-23). They were not re-run for this docs-only
  cleanup.
- Uncommitted on your machine right now: `.gitignore`, `docker-compose.yml` (a dev reload tweak), and this
  documentation cleanup. Nothing has been committed.

## Open risks and chores (yours to decide)

| What | Why it matters |
|---|---|
| Public `/pgrst/` endpoint + consent screen set to "Published" | Anyone with a Google account can sign in, and the image-job endpoint is internet-reachable (limited to two tables and to a per-session token). Fine for testing, close it before real users |
| Dev-to-prod tunnel not rebuilt | Local Image Lab warm sessions can't reach your laptop's PostgREST. The compose file still points at the dead Oracle IP |
| Backups only on the VM | If the VM is lost, so are the dumps |
| Generative Language API | Make sure it is enabled on the Google Cloud project behind your Gemini key, or Gemini chat fails |
| Drive housekeeping | Merge duplicate "PAWN" root folders; delete the stray Kaggle notebook `pawn-image-flux-1-schnell` |
| Client-side encryption | Code exists but is not switched on |

## What is planned next

Nothing in flight. Queue (see `workspace/plan/README.md`): realism models and prompt presets for Image Lab,
a few Image Lab follow-ups that need a real Kaggle session, and refreshing NVIDIA model entries.

## Where to find things

| You want | Open |
|---|---|
| Project pitch and tech overview | `README.md` |
| Deploy, secrets, Nginx, backups, rollback | `deployment.md` |
| This page | `workspace/OVERVIEW.md` |
| Live status for AI sessions | `workspace/current_state.md` |
| Which doc is for whom | `workspace/README.md` |
