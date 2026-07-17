# Plan: Promote `dev` → `main` and release to prod (`pawnai.duckdns.org`)

*Written 2026-07-17. Planning only — no live/production step below has been
executed. Nothing here touches `origin/main` or prod's VM/database until the
user explicitly says go. See "Go/no-go" at the bottom before starting.*

*This is the one-time plan for **this specific release**. The general,
reusable runbook (secrets, Nginx config, firewall rules, first-deploy steps)
lives in root-level `deployment.md` — that VM already exists and is already
serving prod (unlike the 2026-07-14 promotion, this is a routine **update**
release, not a first deploy). This plan only sequences what THIS release
needs on top of that runbook's §5 "Release / update workflow": 2 manual SQL
migrations, and confirming the pre-deploy gate actually passes.*

---

## 0. What's shipping in this release

`main`/`origin/main` was last promoted 2026-07-14 (`f7263f5`). Local `dev` is
now **48 commits ahead**, and **`origin/dev` is 42 commits behind local
`dev`** — almost all of this work exists only on this machine right now.
Same risk the last promotion flagged: push `dev` to `origin/dev` first,
independent of whether the promotion continues same-session.

At a glance, this release ships:

- **Chat feature batch (F-1 through F-11)**: chat-triggered `generate_image`
  tool (forced-SDXL, always warm-session), Groq-priority resolver fix,
  half-generation/empty-reply fix in the closing-synthesis path, Projects
  gallery page + descriptions, sidebar collapse/kebab-menu/scroll fixes,
  attach-image Q&A (F-11) with live-rendered generated images + download
  button in the main reply area.
- **imageLab quality program Q1 (complete)**: SDXL-native resolution buckets
  (fixes half-generated/cropped bodies), fp16 VAE fix (fixes black images),
  DPM++ 2M SDE Karras scheduler + tuned CFG/steps defaults, seed control +
  FLUX negative-prompt honesty, per-model Advanced Params config classes.
- **imageLab quality program Q3 (Q3.1–Q3.3 complete, Q3.4 optional spike
  still open)**: vision-grounded LLM prompt enhancer (Groq→Gemini→raw
  fallback chain), default photoreal negative prompts, style-preset registry
  + a new orthogonal subject-type axis (9 style presets × 4 subject types).
- **imageLab G1 (complete)**: Generations tab delete/edit/reorder-queue,
  settings popover, input-image tag, Refine/Edit full-params pre-apply.
- **Two small polish fixes** (today, 2026-07-17): chat attachment shown as a
  card on the sent message; the Generations "Latest" preview now reflects
  real history and clears when its job is deleted.
- **Registry refresh**: `endpoints.json`/`models.json` updated (rate limits,
  `supports_vision` field, catalog sync) — ships automatically via the
  existing `./backend/data:/app/data` bind mount, no extra deploy step.
- **Dev-only infra** (`1006f48`): cloudflared→SSH reverse-tunnel replacement
  for local warm-session testing. **Explicitly does not touch prod** — zero
  app code or `docker-compose.prod.yml` changes; documented in root
  `deployment.md` §9 as VM-side additive infra this release's deploy step
  doesn't need to touch (it was already set up live, out of band, on
  2026-07-17).

Per `workspace/status/build_tracker.md` / `workspace/current_state.md`, every
item above is marked done, with live Chrome/Kaggle verification on the local
stack where applicable. Q2 (realism checkpoint models) and Q3.4 (negative
embeddings spike) are **not** in this release — still open, deliberately
deferred.

---

## 1. Pre-flight — already run, this session (2026-07-17)

All against local `dev`, HEAD `961710b`:

- [x] `docker compose exec backend pytest -n auto -q` → **580 passed**.
- [x] `docker compose exec frontend npx tsc --noEmit` → clean.
- [x] `docker compose exec frontend npx vitest run` → **37 passed**.
- [x] `docker compose exec frontend npm run build` → clean production build
      (one pre-existing "chunk >500kB" advisory warning, not new, not an
      error).
- [x] `docker compose -f docker-compose.prod.yml build backend` → prod
      Docker image builds clean (catches any prod-specific Dockerfile
      breakage before it hits the VM).
- [x] `git status --porcelain` → clean working tree, nothing uncommitted.
- [x] Confirmed no new server-side secrets needed (`config.py`/`constants.py`
      diff has no new `read_secret` calls — the only `constants.py` additions
      are a static bundled-data path and in-process `ROLE_LEVELS`/threshold
      constants).
- [x] Confirmed only `.example`/`.gitkeep` files are tracked under
      `secrets/` — no real secret ever committed in this batch.
- [x] Confirmed the 2 new registry data files
      (`backend/data/registry/image_presets.json`,
      `endpoints.json`/`models.json` changes) ship via the existing bind
      mount — no extra deploy action.
- [x] Confirmed `scripts/promote-to-main.sh` is intact and unchanged (the
      "silently dies before the final commit" bug found+fixed in an earlier
      promotion has not regressed).
- [x] Grepped the full diff for `TODO`/`FIXME`/`XXX`/`HACK` markers — none
      found.

**Not yet done — needs the user's go-ahead per standing instruction (prod
deploys only in an explicit deployment session):**
- [ ] Push local `dev` → `origin/dev` (backup step, zero prod risk).
- [ ] Everything from §2 onward below.

---

## 2. Two manual SQL migrations (additive, non-destructive)

Both are `add column if not exists` — safe, reversible, no data loss risk,
**unlike** the 2026-07-14 promotion's destructive `memory_chunks` wipe. No
backup-then-accept-data-loss tradeoff this time; still take the routine
backup in §5 anyway.

1. `postgres/migrations/2026-07_Q31_enhance_prompts.sql` — adds
   `image_jobs.original_prompt` / `image_jobs.enhanced_prompt` (text,
   nullable).
2. `postgres/migrations/2026-07_G1_image_jobs_queue_pos.sql` — adds
   `image_jobs.queue_pos` (double precision, nullable) + an index on
   `(session_id, queue_pos)`.

Apply both after the code deploy (§3 of root `deployment.md`'s release
workflow), same pattern as every prior migration:
```bash
cd /opt/pawn
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  exec -T postgres psql -U pawn -d pawn < postgres/migrations/2026-07_Q31_enhance_prompts.sql
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  exec -T postgres psql -U pawn -d pawn < postgres/migrations/2026-07_G1_image_jobs_queue_pos.sql
```
Both are idempotent (`if not exists`) — safe to re-run if a step is repeated.

---

## 3. Release steps (mirrors root `deployment.md` §5, this release's specifics)

1. **Local machine**: `scripts/promote-to-main.sh` (merges `dev` → `main`,
   strips `.claude/`/`workspace/`/`CLAUDE.md`/`AGENTS.md`), review the
   result, then `git push origin main`.
2. **VM** (`ssh` to `144.24.119.184`, `/opt/pawn`):
   ```bash
   git pull origin main
   cd frontend && npm ci && npm run build && cd ..
   docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
   curl -fsS http://127.0.0.1:8001/health
   ```
3. Apply the 2 migrations (§2 above).
4. Run the verification checklist (§4 below).

---

## 4. Verification checklist

Root `deployment.md` §6's standard checklist, plus this release's
new-surface items:

- [ ] `GET /health` → `{"status":"ok"}` over HTTPS, valid cert (unchanged
      baseline check).
- [ ] App loads, no new CSP violations in the browser console.
- [ ] A chat with a PDF attachment → the sent message shows the new
      filename/type card, composer chip clears after send.
- [ ] A chat with an attached image → vision Q&A works, the new thumbnail
      card shows on the sent message.
- [ ] Image Lab: start a warm SDXL session, generate one image. Confirm the
      "Latest" preview shows it immediately (no need to have this browser
      session be the one that generated it — that's the whole point of
      today's fix). Delete that generation from the Generations panel,
      confirm "Latest" updates/clears accordingly.
- [ ] Image Lab G1: queue 2+ jobs, use the up/down arrows to reorder,
      confirm the reordered one actually runs first; delete a queued job,
      confirm it never runs; click Edit on a queued job, confirm it's
      removed and the composer pre-fills correctly.
- [ ] Image Lab Q1/Q3: generate one SDXL image with a style preset and no
      manual negative prompt — confirm no black/half-generated output, and
      the row's settings popover shows the preset used.
- [ ] **Important, not a blocker**: any Kaggle kernel that was already
      running/warm from BEFORE this release is still executing the OLD
      notebook template (VAE fix, scheduler, seed handling, and the new
      `queue_pos` dequeue order only take effect on a freshly pushed
      notebook). Existing users should click "Redeploy" in Image Lab to
      pick up the new template — flag this to the user post-deploy, not
      something the deploy script itself can force.

---

## 5. Data safety & rollback

Same as root `deployment.md` §7 — take the routine backup before starting
(not because this release has a destructive migration; just the standing
practice):
```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  exec -T postgres pg_dump -U pawn pawn > pawn_prod_$(date +%F).sql
```
Rollback: `git checkout <previous-sha>` in `/opt/pawn`, rebuild frontend,
`up -d --build`. Both migrations only ever *add* nullable columns — a code
rollback after they're applied is harmless (older code simply never reads
the new columns); no separate migration-rollback step needed.

---

## 6. Known deferrals (unchanged, carried from root `deployment.md` §8)

- PostgREST's `/pgrst/` still uses the permissive `pawn_anon` role
  (session-token RLS only, not scoped per-session JWT) — unchanged this
  release, still mandatory to close before ever flipping OAuth
  consent to Production/public.
- Client-side encryption remains foundation-only, unwired.
- Private/public repo mirror still parked.

---

## Go/no-go

Ready to execute. Recommended before starting:

1. Confirm you're fine with the standard release flow (no destructive
   migration this time — lower risk than the last promotion).
2. Have the pre-flight gate (§1) trusted — it already passed this session,
   but if meaningful time passes before executing, re-run it rather than
   trusting a stale result.
3. Say go for §2 onward (push `dev`, promote, deploy) whenever ready — per
   your instruction, I'll wait for that signal before touching
   `origin/main` or the VM.
