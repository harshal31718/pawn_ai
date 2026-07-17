# Plan: Promote `dev` → `main` and deploy to the Oracle VM

*Written 2026-07-14. Planning only — no live/production step below has been
executed. Nothing here touches the Oracle VM, `origin/main`, or prod's
database until a human explicitly runs it. See "Go/no-go" at the bottom
before starting.*

*This is the one-time plan for **this specific, large promotion**. The
general, reusable runbook (secrets, Nginx config, firewall rules, etc.)
already lives in root-level `deployment.md` — this plan sequences the extra
steps this particular promotion needs (unpushed commits, 3 manual SQL
migrations, one of them destructive) on top of that runbook, and doesn't
repeat content that hasn't changed.*

---

## 0. Why this promotion is bigger than a normal release

`main` was last promoted 2026-07-05 (`b92e883`, currently also `origin/main`
— confirmed up to date). Local `dev` is **69 commits ahead**, and
**`origin/dev` itself is 27 commits behind local `dev`** — most of this
work was never pushed to GitHub at all, only committed locally across
several sessions. That's a real risk independent of deployment: if this
machine's local repo were lost right now, ~4 weeks of work (all of Phase A,
M, N, O, P) would be unrecoverable from GitHub. **Step 1 below (push `dev`)
fixes that regardless of whether the promotion continues same-session.**

What's actually shipping in this promotion, at a glance:

- **Phase A — Chat Agent Refinement**: native tool calling, `web_search` +
  `fetch_url` (internet access), `doc_search`, heuristic+LLM model router,
  LangGraph orchestrator rebuild (plan → tool-loop → final), 3 preset
  subagents, full trace persistence.
- **Phase M — Memory Scoping**: chats/projects scoped RAG, replaces the old
  cross-chat-visible memory design outright (schema change, see §3).
- **Phase N — Interleaved Agent Streaming**: execute+final merge.
- **Phase O — Reply Quality**: plan-as-contract verifier, mid-loop
  double-answer fix, deep-research fetch+extract.
- **Phase P — UI**: sidebar search relocation, kebab menu, project page,
  trace toggle, row-height fixes.
- **Image Lab fixes**: local-dev tunnel/migration unblock, dead-session
  detection (Kaggle kernel-status probe + notebook write-hardening),
  Warming-pill substatus/elapsed display, session start/extend/stop error
  surfacing.
- **Cleanups**: dead `EndpointEntry.secret` field removed, deterministic
  Drive root-folder resolution, swallowed-exception logging.

Per `workspace/status/build_tracker.md` / `workspace/current_state.md`,
Phases A/M/N/O/P are all marked code-complete with live verification done
against the local dev stack. Re-confirm that's still true before promoting
(§1) — don't take the doc's word for it blind.

**Not in scope for this promotion — separate decision, see §7:** the FLUX
CUDA-OOM fix (branch `worktree-flux-oom-fix`, PR #2) is drafted but not
merged to `dev` and not yet verified on real Kaggle hardware.

---

## 1. Pre-flight — verify locally before touching anything remote

Run from a clean `dev` checkout (not a worktree — worktrees are fine for
drafting a change, but do this gate from the real `dev` working copy since
that's what gets pushed and promoted):

1. `git status` clean on `dev`, no stray uncommitted files.
2. `docker compose exec backend pytest -n auto` → expect 438 passed. Run
   twice — there's a known pre-existing xdist/SQLite-lock flake on 1-2
   `test_chat.py` tests that clears on retry; anything that fails
   *consistently* on both runs is real and blocks promotion.
3. `cd frontend && npx tsc --noEmit && npm run build` → clean, no errors.
4. `docker compose config` (both `docker-compose.yml` and
   `docker-compose.prod.yml` via `--env-file`) → valid, no syntax errors.
5. Skim `workspace/status/build_tracker.md`'s top summary — confirm no
   phase is still marked `[~]` (in progress) or has an open live-verification
   checklist item you're not aware of.
6. Decide the FLUX-fix question now, not mid-promotion — see §7.

If all green, continue. If anything fails, fix it on `dev` first — never
promote a red gate.

---

## 2. Push `dev`, then promote to `main`

```bash
# From the real dev checkout (not this worktree):
git push origin dev                # closes the 27-commit local-only gap — do this even if pausing here

scripts/promote-to-main.sh         # merges dev -> main, strips .claude/ + workspace/ + CLAUDE.md/AGENTS.md
# review the result:
git diff origin/main main --stat   # sanity check — should be "everything except docs", nothing unexpected
git push origin main
```

`scripts/promote-to-main.sh` already handles the doc-stripping merge
correctly (see its own header comment for why a plain `git merge` can't be
used) — no changes needed to the script itself for this promotion.

---

## 3. Manual DB migrations — apply BEFORE restarting the backend, IN THIS ORDER

Prod's Postgres volume was initialized 2026-07-04, before any of Phase M
existed — it is still running the **original pre-Phase-M schema**
(`match_memory_chunks`/`search_memory_chunks`, `memory_chunks` with no
`scope_type`/`scope_id`/`kind`/`doc_id`). `postgres/schema.sql` only runs
`docker-entrypoint-initdb.d`-style on a brand-new empty volume, so a plain
`git pull` + restart does **nothing** to an already-initialized volume like
prod's — these three files must be applied by hand, and the first one is
destructive. Order matters: the second migration's `DROP FUNCTION` targets
the exact signature the first one creates.

```bash
cd /opt/pawn
docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T postgres \
  psql -U pawn -d pawn < postgres/migrations/2026-07_memory_scoping.sql

docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T postgres \
  psql -U pawn -d pawn < postgres/migrations/2026-07_doc_search_kind_return.sql

docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T postgres \
  psql -U pawn -d pawn < postgres/migrations/2026-07_image_sessions_stop_requested_at.sql
```

**⚠️ `2026-07_memory_scoping.sql` drops and recreates `memory_chunks` —
every real user's existing memory/RAG history on prod is wiped, not
migrated (per `plan_memory_scoping.md` decision #10: old rows carry no
scope information to migrate to).** This is real user data loss, not a
reversible step short of a pre-migration `pg_dump`. **Needs your explicit
go-ahead before this step runs** — do not run it as part of an unattended
sequence. Take the backup in §6 first regardless.

The third migration (`stop_requested_at`) is additive-only, no data loss —
low risk, but still can't be skipped or `stop_session()` 500s.

After all three: sanity-check with
`\d memory_chunks` and `\d image_sessions` in a `psql` session — confirm
`scope_type`/`scope_id`/`kind`/`doc_id` and `stop_requested_at` exist before
moving on.

---

## 4. New dependencies — covered by `--build`, no extra action, flagging for awareness

- `backend/requirements.txt`: `+trafilatura` (Phase A.3 `fetch_url`'s
  readable-text extraction — a real runtime dependency, not dev-only),
  `+pytest-xdist` (test-only).
- `frontend/package.json`: `+remark-gfm` (already vetted — this was the
  "missing from package-lock.json entirely" bug fixed earlier on `dev`;
  confirm `npm ci` succeeds cleanly in §5, not just `npm install`).

Both come along automatically via `docker compose ... up -d --build` (backend)
and `npm ci && npm run build` (frontend) in the existing runbook — no manual
step beyond what §5 already does.

**No new Docker secrets, no new `.env.prod` variables.** Checked
`.env.prod.example` and every provider-key usage (`web_search`'s `api_key`
comes from the requesting user's own BYOK settings via `ctx`, same as every
LLM call) — PAWN's BYOK-only model means none of Phase A's new tools need a
shared prod-side credential.

---

## 5. Deploy steps (follow root `deployment.md` §3.4–3.9, unchanged)

No changes needed to the Nginx config, firewall rules, or TLS setup from
the existing runbook — this promotion adds no new routes, no new exposed
ports, no new domains. In order:

1. `cd /opt/pawn && git pull origin main` — first confirm `git status` is
   clean on the VM (no local drift) before pulling, since
   `backend/data/registry/*.json` are git-tracked files the pull will
   overwrite; if the VM has uncommitted local changes there, reconcile
   before pulling, don't just force it.
2. Run the 3 migrations from §3 — **before** the next step, so the new
   backend code never queries a schema it doesn't have yet.
3. `cd frontend && npm ci && npm run build` (rebuilds `dist/`, served by
   Nginx).
4. `docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build`
5. `docker compose ... ps` — confirm all containers `Up`/`healthy`.
6. `curl -fsS http://127.0.0.1:8001/health` → `{"status":"ok"}`.

---

## 6. Backup first (before §3, not after)

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  exec -T postgres pg_dump -U pawn pawn > pawn_prod_$(date +%F)_pre_promotion.sql
```

Root `deployment.md` §7 already documents this — repeating here because
§3's destructive migration makes it non-optional for *this* deploy
specifically, not just routine hygiene.

---

## 7. Open decision: is the FLUX OOM fix in scope for this promotion?

**Recommendation: no, not this round.** `worktree-flux-oom-fix` (PR #2) is
a notebook-only change, drafted but explicitly **not verified on real
Kaggle hardware** (blocked on your local network this session). Bundling an
unverified prod-affecting notebook change into the same promotion as ~70
already-verified commits means a FLUX-specific problem discovered later
can't be isolated from "did the big promotion break something." Cleaner to:

1. Ship this promotion first (Phases A/M/N/O/P + imagelab fixes), verify
   prod is healthy.
2. Separately, once you're off the restricted network: run a live FLUX
   warm-session generate locally to confirm the `max_memory` cap actually
   fixes the OOM.
3. If confirmed, merge PR #2 to `dev` and ship it as its own small,
   easy-to-attribute follow-up promotion.

If you'd rather bundle it anyway (e.g. to avoid a second deploy cycle),
merge PR #2 into `dev` before §1's pre-flight gate, and mark the OOM fix as
"code-shipped, live-unverified" in the release notes rather than "fixed" —
same posture as this project's `deployment.md` already uses for parts of
Image Lab.

---

## 8. Verification checklist — after deploy

Everything in root `deployment.md` §6 (health, CSP, OAuth round-trip, Drive
link, BYOK chat streaming, one Kaggle SDXL image-gen job), **plus** these
new-to-this-promotion checks:

- [ ] A chat turn that should trigger a tool call (e.g. "search the web
      for...") actually calls `web_search`/`fetch_url` and the trace shows
      it (Phase A).
- [ ] Upload a document, ask a question about it → `doc_search` retrieves
      the right chunk with a citation, not a hallucinated answer (A.4).
- [ ] Create a project, move a chat into it, confirm memory retrieval stays
      scoped (a chat outside the project shouldn't surface the project's
      memory, and vice versa) — this is the entire point of the destructive
      §3 migration, so it's the one check that most needs to pass.
- [ ] A heavy/research-tier prompt produces exactly one final answer, not
      two (Phase O.1 regression this whole phase fixed).
- [ ] Image Lab: start a warm session, let it run past ~90s without a
      heartbeat landing (or force it by misconfiguring `POSTGREST_PUBLIC_URL`
      temporarily) → confirm the new dead-kernel probe surfaces a precise
      error instead of hanging on "Warming" for 15 minutes.
- [ ] Sidebar search, project page, kebab menu (Phase P) — quick click-through,
      no console errors.

---

## 9. Rollback

Same as root `deployment.md` §7: `git checkout <previous-sha>` in
`/opt/pawn` (i.e. back to `b92e883`), rebuild frontend, `up -d --build`.
**The §3 migrations do NOT roll back with a code rollback** — a code
rollback after the memory_chunks wipe still leaves the old schema gone.
If you need to undo the DB migration itself, restore from the §6 backup
(`psql -U pawn -d pawn < pawn_prod_<date>_pre_promotion.sql` into a fresh
DB, or accept the data loss if rollback is only needed for a few hours of
code issues, not schema issues).

---

## 10. Known deferred risk, carried forward unchanged

Root `deployment.md` §8 already flags this and it's still true after this
promotion: PostgREST's `/pgrst/` endpoint uses the permissive `pawn_anon`
role with only session-token RLS, not per-session scoped JWT. Fine while
the Google OAuth consent screen stays in Testing mode with an allowlist;
must be closed before ever flipping it to Production/public. Nothing in
this promotion changes that posture either way.

---

## Go/no-go

This plan is ready to execute, but **do not run §2 onward without an
explicit go-ahead** — specifically because of §3's destructive migration
and because this is, by commit count, the largest single promotion this
project has done. Recommended before starting:

1. Confirm you're fine with prod's existing `memory_chunks` (real user RAG
   history since 2026-07-04) being wiped, not migrated — the backup in §6
   is the only recovery path afterward, and it's a manual restore, not a
   live fallback.
2. Confirm the FLUX-fix scoping call in §7 (recommend: exclude from this
   round).
3. Have the pre-flight gate (§1) actually pass, not assumed from docs.

Once you confirm, this plan can be executed in one sitting — nothing in it
requires an overnight wait or a second calendar day.
