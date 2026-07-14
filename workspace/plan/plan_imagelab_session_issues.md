# Plan: Image Lab warm-session issues

Status: **IN PROGRESS — resumed 2026-07-14.** Local-dev session-start/stop
bugs found and fixed this session (all committed to `dev`, live-verified
against a real Kaggle kernel). The separate production issue (notebook
auto-fails, PAWN never finds out) is diagnosed with a strong, code-verified
root cause below but **intentionally NOT fixed yet** — user's explicit
instruction: fix dev, diagnose prod, do not change prod-affecting code until
an actual deployment session (out of scope for now). See §2026-07-14 below.

**User flagged a fresh Kaggle failure log the same day (marked "critical,
save for later, complete at last")** — real Kaggle log, `gaierror: Name or
service not known` resolving `channels-lap-because-tcp.trycloudflare.com`
inside cell-1 (`patch_session({"status": "installing"})`). **This is NOT a
new/unexplained bug**: that hostname is the exact dev tunnel URL from this
session's local-dev verification above, which was intentionally stopped
(`docker compose stop cloudflared`) once verification finished — quick
Cloudflare Tunnels don't persist their hostname across restarts, and
`docker-compose.override.yml` still points at the now-dead URL. Any new
local session-start attempt will hit this until the tunnel is restarted and
the override file is updated with the new URL (steps in
`docker-compose.override.yml.example`). **Deliberately not fixed now** — user
asked to defer and finish other work first; only action needed later is
restarting the tunnel, not a code fix. Kept separate from the actual
production fire-and-forget-writes diagnosis above, which this log does
*not* newly confirm (it's a dev-side DNS failure, not evidence about prod's
real PostgREST reachability).

---

## 2026-07-14 session — dev fixed, prod root-caused (not fixed)

### Local dev: "session is not starting" — FIXED, 2 separate bugs found

1. **UI silently swallowed the start/extend/stop error.**
   `ImageGenerator.tsx`'s `handleHeaderStart/Extend/Stop` caught the API
   error and only `console.error`'d it — never called `setError`, so the
   header Start button just silently reset with no visible feedback. Fixed:
   all three handlers now call `setError(err.message)`. Commit
   `97173a4`.

2. **`POSTGREST_PUBLIC_URL` has been blank in dev since the D.3/D.4 Postgres
   migration — a real regression, not an always-existing limitation** (the
   old code comment claiming "same as it did under Supabase" was wrong and
   has been corrected). Before commit `9350664` (2026-07-03, Supabase ->
   self-hosted Postgres+PostgREST), `SUPABASE_URL` was a real public cloud
   endpoint reachable from anywhere including Kaggle, regardless of where
   the backend ran — so local warm-session testing worked with zero extra
   setup. Self-hosted PostgREST runs as a local-only Docker container with
   no public URL, so `start_session()` has 412'd for every local dev session
   since that migration. Fixed with a dev-only tunnel: `docker-compose.yml`
   gained a profile-gated `cloudflared` service (`docker compose --profile
   tunnel up -d cloudflared`), plus `docker-compose.override.yml.example`
   documenting how to wire the printed `https://*.trycloudflare.com` URL
   into `POSTGREST_PUBLIC_URL` for local runs only. Zero effect on
   `docker-compose.prod.yml` or default `docker compose up`. Commit
   `30d5825`.

3. **Found while live-verifying #2: `stop_session()` 500'd** with
   `psycopg.errors.UndefinedColumn: column "stop_requested_at" of relation
   "image_sessions" does not exist`. Root cause: commit `472a170`
   (2026-07-05) added `image_sessions.stop_requested_at` to `schema.sql` but
   shipped no migration for already-initialized Postgres volumes (`schema.sql`
   only runs via `docker-entrypoint-initdb.d` on a brand-new volume) — this
   dev machine's volume predates that column. Added
   `postgres/migrations/2026-07_image_sessions_stop_requested_at.sql` and
   applied it locally. **This same gap may exist in production** if prod's
   Postgres volume was also initialized before 2026-07-05 and this migration
   was never run there — check `\d image_sessions` on the prod DB before
   assuming Stop works there. Commit `30d5825`.

Live-verified end-to-end against a real Kaggle kernel through the tunnel:
Start -> Warming -> job queued -> Stop -> Stopping -> honest "kernel didn't
confirm exit in time" after the 30s grace window (expected, kernel was still
installing deps). The full warm-session plumbing genuinely works locally now.

### Production: "notebook starts, auto-fails, app stuck showing 'warming',
### notebook closed on Kaggle's side" — DIAGNOSED, NOT FIXED (out of scope)

Read both `image_flux_session` and `image_sdxl_session` notebooks
(`backend/app/kaggle_templates/image_{flux,sdxl}_session/notebook.ipynb` —
byte-identical structure) end to end. **Primary, code-verified finding:**

**`patch_session()` / `patch_job()` never check the HTTP response.** Every
read function (`get_session()`, `next_job()`) calls `r.raise_for_status()`
and would raise on a PostgREST rejection. Neither write function
(`patch_session()`, `patch_job()`) does — they fire the `requests.patch(...)`
and discard the response entirely, success or failure:

```python
def patch_session(fields):
    requests.patch(f"{REST}/image_sessions", headers=HEADERS,
                   params={"id": f"eq.{SESSION_ID}"}, json=fields, timeout=20)
    # no .raise_for_status(), no response check at all
```

This means **every status/heartbeat/error write in the notebook is
fire-and-forget**. If PostgREST ever rejects a write — RLS `session_token`
mismatch, a schema drift like the `stop_requested_at` gap found above, a
transient PostgREST 5xx, or the row simply not matching the RLS policy for
any reason — the notebook code has **no way of knowing the write didn't
land**, and nothing retries or surfaces it. Concretely, this explains the
exact symptom reported ("not even informing the app"):

- Cell-2's model-load failure path (`except Exception as e:
  patch_session({"status": "error", ...}); raise`) LOOKS like it reports the
  failure honestly, but if that specific `patch_session` call is silently
  rejected by PostgREST, the session row is never updated to `'error'` —
  the exception still propagates and Kaggle tears down the kernel ("the
  notebook is closed due to some failure"), but PAWN's `image_sessions` row
  is stuck at whatever status it last successfully wrote (`'installing'` or
  `'loading_model'`), which is exactly "app shows warming mode" persisting
  after the real failure.
- The supervisor thread's heartbeat write has the same blind spot, AND is
  additionally gated behind a successful *read* first
  (`_supervisor()`: `if not _sess: continue` skips the heartbeat patch too
  when `get_session()` returns nothing) — this was plan hypothesis #2
  ("RLS token on reads"), now more precisely: even a transient read hiccup
  skips that cycle's heartbeat, and a persistent one means `heartbeat_at`
  never lands at all, forcing `get_session_status()`'s dead-session
  detection onto the 900s (15 min) wall-clock fallback instead of the 90s
  heartbeat-staleness check — a long, silent-feeling wait that reads exactly
  as "not even informing the app."
- Secondary, smaller gap: cell-1 (dependency `pip install`) has **no
  try/except at all**, unlike cell-2's model-load. A `pip install` failure
  (version conflict, transient PyPI blip, Kaggle base-image drift) raises
  uncaught with zero attempt to report it — relies entirely on the same
  blind heartbeat-staleness/900s fallback above.

**Net: the notebooks' error-reporting design assumes every PostgREST write
succeeds, and nothing in the code can tell when that assumption is false.**
This is a plausible, well-supported explanation for the reported production
behavior, but is *unverified against real Kaggle/PostgREST logs* (no Kaggle
access from this environment) — the next production debugging session
should first check kaggle.com's kernel log for the actual last-printed line
before the run ended, and cross-check the `image_sessions` row's last
successfully-written status/heartbeat_at against that timestamp, to confirm
a write was in fact silently dropped rather than something else entirely
(e.g. a genuine OOM crash that also killed the write attempt itself, which
this fix wouldn't help — see the FLUX OOM item below).

**Fix sketch for a future session (NOT applied — out of scope until
deployment, per explicit instruction not to touch prod-affecting code now):**
add `.raise_for_status()` (or at least log + retry-once) to `patch_session`/
`patch_job` in both notebooks, and consider making the supervisor's
heartbeat write independent of a successful read (it currently only reaches
the heartbeat patch after `get_session()` succeeds).

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
