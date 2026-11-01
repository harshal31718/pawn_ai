# PAWN — Current State

**Audience: AI agents.** A short snapshot of what is true NOW. Reasoning/history lives elsewhere:
- Why decisions were made: `workspace/decisions/change_log_2026.md`
- What every module does + API reference: `workspace/CODEBASE_MAP.md`
- Day-by-day history: `workspace/status/dev_log.md`; step ledger: `workspace/status/build_tracker.md`
- Old narrative version of this file (through 2026-07-23): `workspace/archive/current_state_history_to_2026-07-23.md`

Last reconciled: **2026-11-01** (after deploy of `a04b2ea`). Update this file (replace stale lines, do not append a diary) after every step.

---

## Production

| Item | Value |
|---|---|
| URL | `https://pawnai.duckdns.org` (DuckDNS `pawnai` -> `136.114.65.94`) |
| Host | GCP `e2-micro` (Always Free, 1 shared vCPU / 1 GB RAM, x86_64, `us-central1-a`), project `pawn-501409`, deploy user `pawndeploy`, repo at `/opt/pawn` on branch `main` |
| Stack | host Nginx + certbot -> `backend` (127.0.0.1:8001, 500m) + `postgrest` (127.0.0.1:3001, 128m) + local `postgres` (`pgvector/pgvector:pg16`, 200m, no published port). Frontend is a static build in `frontend/dist` served by Nginx |
| DB | LOCAL Postgres container since 2026-10-30. **Supabase is gone** (project deleted). DB was recreated empty that day |
| Backups | `scripts/backup-db.sh`, cron 03:30 UTC, keeps 7 in `/opt/pawn/backups`; dumps die with the VM |
| Deployed `main` | `a04b2ea` (2026-11-01; code identical to `dev`, docs stripped). Previous verified-stable: `4b97c2a` (2026-10-30, live Google login verified) |
| History | Oracle Cloud VM terminated by Oracle 2026-08-30 -> GCP same day (see change log) |

Runbook: `deployment.md` (root). Do not run `docker compose down -v` on the VM.

## Branches

- `dev` = working branch, has all docs. `main` = deploy-only, docs stripped by `scripts/promote-to-main.sh`.
- Deploy files (`docker-compose.prod.yml`, `deployment.md`, `scripts/backup-db.sh`) are identical on both.
- `main` and `dev` have identical non-doc content as of 2026-11-01; `dev` additionally holds the docs. Nothing is unpromoted.
- Backend restarts take ~1.5 min to accept connections on the VM (0.5 CPU); a 502 during that window is normal.
- `workspace/stable_commits.md` lags (its `dev` row predates the 10-30 sync); only update it when the user says so.

## What exists (feature level)

- Multi-provider chat over 11 providers / 47 endpoints / 31 models (28 active), OpenAI-compatible wire format, capability-first routing, 90% soft-block + 429 cooldown, cross-endpoint and cross-model failover mid-stream (only before the first token).
- LangGraph agent: classify -> direct_answer | plan -> execute (native tool calling, subagents depth 1) -> verify. Tools: calculator, datetime, fetch_url (SSRF-guarded), web_search (user BYOK Tavily/Brave), search_memory, doc_search, generate_image.
- Auth: Google OAuth (confidential client, `drive.file`) + email/password (Argon2id), 7-day HS256 JWT. Single hardcoded admin email.
- Keys: per-user BYOK (AES-256-GCM in Postgres) with an operator pool fallback (admin-managed, fair-share quota). `key_source: either` is BYOK-first.
- Storage: all user content (chats, summaries, RAG source chunks, uploads, projects) in the user's Google Drive, `PAWN/` (prod) or `PAWN-dev/` (`PAWN_ENV=dev`). Postgres holds accounts, encrypted keys/tokens, embeddings, usage, image jobs.
- Memory: per-chat / per-project scoped RAG (pgvector + FTS, RRF), `gemini-embedding-2` 768-dim, BYOK-first then pool key.
- Image Lab: SDXL + FLUX.1-schnell on the user's Kaggle account; warm sessions rendezvous through public PostgREST (`/pgrst/`, RLS by `X-Session-Token`); durable cold jobs; img2img; vision prompt enhancement.
- Frontend: React 19 + Vite 8 + Tailwind v4; optimistic UI with persisted sync queue; Providers page (Models / Providers / Admin tabs).

## Gates (last known)

- Backend: 801 pytest tests green as of 2026-07-23 (`docker compose exec backend pytest -n auto`). Not re-run during the 2026-11-01 docs-only pass.
- Frontend: `npm run build` (tsc + vite) is the gate; 4 vitest files exist (`crypto`, `AdvancedParams`, `advancedParamsConfig`, `GenerationsPanel`).
- No CI in the repo.

## Known issues and deferrals (open)

Security / ops
- `/pgrst/` is publicly reachable; `pawn_anon` is limited to the two image tables and RLS-scoped by session token, but a scoped per-session JWT is still deferred and is **mandatory before real multi-user**. The OAuth consent screen is Published, so any Google account can sign in. Close this before real usage.
- Client-side (WebCrypto) encryption is foundation-only and unwired.
- Local-dev tunnel to prod PostgREST not recreated on GCP; `pgrst-tunnel`/`keys-tunnel` in `docker-compose.yml` still point at the dead Oracle IP `144.24.119.184`. Local warm-session testing needs the tunnel redone.
- Prod has no `pool_*` Docker secrets; pool keys exist only via the admin UI/DB.
- Check that the Generative Language API is enabled on the Google key's GCP project (chat via Gemini failed before for this reason).
- Dumps in `/opt/pawn/backups` live on the same disk as the DB; copy off-box periodically.
- 1 GB RAM: frequent container restarts mean it is time for `e2-small`.

Code
- Kaggle warm-session notebooks' `patch_session()`/`patch_job()` do not check HTTP responses, so a rejected write silently loses error/heartbeat reports (diagnosed 2026-07-14, deliberately unfixed outside a deploy session).
- Test suite reads real dev Postgres for pool keys/usage in places; autouse stubs paper over it. A per-test DB isolation pass is owed.
- `DummyResolver.pick` returns 5-tuples where `normalize.py` unpacks 6; `routes/chat.py` has a stale hardcoded provider list for model-id validation; `record_429` ignores `Retry-After`; frontend rate-limit countdown may be unreachable from the chat route. Full list: `CODEBASE_MAP.md` section 13.
- `append_messages`/`append_rag_chunks` re-upload whole files per turn; fine at current scale.
- `memory_chunks` ivfflat index uses `lists = 10`; retune as data grows.
- Model schema (`workspace/schemas/model_schema.md`) is documented but not implemented.

Manual cleanups owed by the user
- Merge duplicate "PAWN" root folders in Drive; delete orphaned Kaggle kernel `pawn-image-flux-1-schnell`.

## Planned work

See `workspace/plan/README.md` (order: imageLab Q2/Q3.4, imageLab open items I-2..I-5, providers NIM refresh). Nothing is in flight. videoLab is deferred indefinitely.
