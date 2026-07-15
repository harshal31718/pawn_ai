# Plan: Image Lab — Remaining Open Items (slim, active)

*Created 2026-07-15 by streamlining `plan_imagelab_session_issues.md` and
`plan_open_issues_2026-07-14.md` — both were ~95% completed work. Full history/diagnosis
moved to `workspace/implemented_phases/plan_imagelab_session_issues_history.md` and
`.../plan_open_issues_2026-07-14_resolved.md`. Only still-open items live here.
Every item verified open against the current dev tree on 2026-07-15
(e.g. `image_flux_session` notebook still has `device_map="balanced"`, no `max_memory`).*

**Rule for all items: additive fixes only — dev is in working condition; no new phases,
no refactors of working paths.**

---

## I-1 — FLUX CUDA OOM on generate (code, ready to land)

**Status:** fix already written on branch `worktree-flux-oom-fix` (commit `ac1390b`,
re-applies the `max_memory` cap to `image_flux_session/notebook.ipynb`) — unmerged because
it is Kaggle-unverified (an earlier draft `84c0a4d` was reverted in `d96c1c6`).

**Steps:**
1. Rebase `worktree-flux-oom-fix` onto current `dev`; template tests + full suite green.
2. Live-verify on a real Kaggle FLUX warm session (needs user creds + fresh tunnel):
   model loads, then ≥2 consecutive generations succeed with no CUDA OOM.
3. Merge to `dev`; delete the worktree branch; update docs.

**Gate:** step 2 is mandatory before merge — this exact fix was reverted once already.

## I-2 — Real-Kaggle live smoke test for the dead-session-detection work (manual + user)

The 2026-07-14 round-7 work (probe, `_rest_patch`, warming substatus) is code-complete,
438 tests green, but never run against a real kernel. Checklist (from the history doc):
1. Restart tunnel: `docker compose --profile tunnel up -d cloudflared`; update
   `docker-compose.override.yml` with the new `trycloudflare.com` URL.
2. Start a real SDXL warm session → observe `Warming · installing deps · 1m 23s`-style
   progression to ready; check the Kaggle kernel log for the new `[pawn]` lines.
3. Kill PostgREST reachability (stop tunnel) mid-warmup → PAWN flips to a precise error
   within ~90 s (not 15 min).
4. While at it, capture the stop/tracking evidence (I-4).

## I-3 — Prod deploy gate (deployment session ONLY — standing instruction)

Next deployment session must include:
1. Deploy the hardened notebook templates (round-7 changes have never shipped to prod).
2. Check prod DB: `\d image_sessions` has `stop_requested_at`; if not, apply
   `postgres/migrations/2026-07_image_sessions_stop_requested_at.sql`.
3. I-1's FLUX fix rides along if merged by then.
4. Add both to `deployment.md`'s checklist so they can't be forgotten.

## I-4 — Stop/tracking hypotheses (needs human Kaggle access, unverified since 2026-07-05)

"Stop still not fully working" was reported but never repro'd with specifics. During I-2's
live session, capture: model, phase when Stop clicked, UI state vs kaggle.com state, the
`image_sessions` row at that moment. Then check, in order: (1) supervisor thread present in
the fresh kernel's log; (2) PostgREST *reads* return the session row (writes working ≠ reads
working — RLS); (3) `os._exit(0)` actually terminates the Kaggle run and frees the GPU
(load-bearing, unverified); (4) frontend bundle is fresh; (5) no orphaned duplicate kernels
on the same slug.
**Verification bar:** Stop during `loading_model` → kaggle.com run ends within seconds AND
UI reflects it; a kernel killed from kaggle.com → PAWN error banner within the stale window.

## I-5 — Minor code follow-up (filler)

- Probe the `stopping` branch in `get_session_status` (currently only warmup is probed) —
  documented follow-up from round 7. Small, test-covered, additive.

## Needs you, not code (carried from the resolved doc)

- Merge the duplicate "PAWN" Drive root folders (manual judgment; app now deterministically
  uses the oldest root, so this is cleanup, not a fire).
- Delete the orphaned `pawn-image-flux-1-schnell` Kaggle kernel.
- (Tunnel restart is I-2 step 1.)
