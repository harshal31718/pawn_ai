# Plan: Image Lab warm-session issues (PAUSED — dev only)

Status: **OPEN / paused 2026-07-05 at user request.** Not deployed to prod as
a "resolved" item — the fixes below are live, but the user confirms problems
still remain. Kept on `dev` for a later focused session. Do NOT promote/deploy
anything from this plan until the user re-engages on it.

---

## Context — what's already been tried (all live on prod as of 2026-07-05)

Three fixes shipped today, in order:

1. `472a170` — `stop_requested_at` column + honest "couldn't confirm exit" /
   stale-`ready` detection in `get_session_status`. Made PAWN *honest* about
   not knowing a session's true state instead of falsely reporting `ended`.
2. `4c33bf8` — **supervisor daemon thread** in both warm-session notebooks
   (`image_flux_session`, `image_sdxl_session`): heartbeats for the kernel's
   whole life and `os._exit(0)`s the instant it sees a stop/expiry, so Stop
   can kill the kernel during *any* phase (not just `ready`). Plus backend
   warmup-death detection via stale heartbeat. Intended to make Stop *actually*
   stop the kernel and to detect mid-warmup death.

Root-cause finding that's solid and should NOT be re-litigated: the warm-session
notebooks' serve-loop + model-load cells are **byte-identical since 06-30**
(verified via `git show`), so none of this is a recent regression — the
stop-only-works-during-`ready` gap has existed since W.1 (06-29). Kaggle has
**no external "cancel kernel" API**; cooperative self-exit is the only stop
mechanism possible.

## Still broken (per user, 2026-07-05)

The user reports session stop / tracking is **still not fully working** after
the supervisor fix. **Specifics were not captured this session** — the next
session MUST get concrete repro details before changing more code:

- Which model? (SDXL vs FLUX — FLUX also OOMs on load, which confounds testing.)
- At which phase was Stop clicked? (starting / installing / loading_model / ready)
- What did the UI show vs. what did kaggle.com show (kernel actually running?)
- Was it a *fresh* session started AFTER the `4c33bf8` deploy? (A kernel already
  running on Kaggle predates the supervisor and will never self-stop — this is
  expected and must be ruled out first.)
- Grab the `image_sessions` row (status, heartbeat_at, stop_requested_at,
  expires_at) and the kaggle.com kernel state at the same moment.

## Leads / hypotheses to check next time (not yet verified)

1. **Is the supervisor thread actually running on the deployed kernel?** Verify
   a *fresh* post-`4c33bf8` session's kernel logs show the supervisor started.
   If a running kernel predates the deploy, that fully explains "still broken."
2. **RLS token on reads.** The supervisor reads `get_session()` via PostgREST
   with `X-Session-Token`. If the token GUC / RLS ever fails to match, reads
   return `[]` → supervisor treats as transient (continues), so it would NEVER
   see the stop and never exit. Confirm reads return the row for a live session
   (heartbeats landing proves *writes* work, but check reads explicitly).
3. **`os._exit(0)` inside a Kaggle kernel** — confirm it actually terminates the
   Kaggle *run* (frees the GPU) and isn't caught/restarted by Kaggle's harness.
   This is the load-bearing assumption of the whole fix and is UNVERIFIED on
   real hardware (no Kaggle access from the dev/agent environment).
4. **Frontend caching** — confirm the user is on the freshly-built bundle, not a
   cached older `ImageGenerator.tsx` that ignores the `error` status.
5. **Orphaned / multiple kernels** — redeploys + OOM retries may have left
   several kernel versions running on the same slug (`pawn-flux-session` /
   `pawn-sdxl-session`), only one of which is bound to the session row PAWN is
   stopping. The others keep running invisibly. Check kaggle.com for stray runs.

## Separate, also-outstanding (paused earlier, same area)

- **FLUX CUDA OOM on generate** — `device_map="balanced"` packs GPU 0 to the
  brim, OOM on the next inference. A `max_memory` cap fix was drafted in
  `84c0a4d` then reverted in `d96c1c6` (the FLUX-notebook revert). Still unfixed.
  Confounds FLUX stop-testing — prefer SDXL for isolating the stop issue.

## Verification bar before calling any of this done

- A *fresh* session, Stop clicked during `loading_model`, → kaggle.com shows the
  run actually ended within ~seconds (GPU freed), AND PAWN UI reflects it.
- A kernel killed from kaggle.com → PAWN flips to an `error` banner within the
  heartbeat-stale window.
- Both must be reproduced live (no Kaggle access from the agent environment, so
  this is a human-in-the-loop verification).
