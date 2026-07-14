# Plan: Image Lab warm-session issues

*Merged 2026-07-14 from three docs: this file's own prior history, the
Image-Lab-specific §1 of `plan_open_issues_2026-07-14.md` (that file's other
sections — §2/§3/§4 — are unrelated subsystems, unaffected, still live
there), and the newly-approved `plan_imagelab_dead_session_detection.md`
(folded in below, now deleted as a standalone file).*

## Status (as of 2026-07-14)

- **DONE, dev, live-verified:** local-dev "session is not starting" (UI error
  swallowing, missing `POSTGREST_PUBLIC_URL` tunnel, missing
  `stop_requested_at` migration) — see "Historical fixes" below.
- **CODE-COMPLETE, dev, all 6 steps done, 438 backend tests green + frontend
  build clean:** backend Kaggle-status probe + notebook write-hardening for
  "notebook auto-fails, app stuck on Warming forever." Frontend Warming-pill
  substatus/elapsed live-verified via Chrome against the real dev stack
  (mocked backend responses — no real Kaggle session started, no GPU quota
  spent). **The one thing NOT done: a live smoke test against a REAL Kaggle
  kernel** (this environment has no Kaggle credentials) — needs the user, a
  restarted dev tunnel, and a real session start/kill. See "Active
  implementation plan" → Step 6 for the exact checklist.
- **DEFERRED, gated on a real deployment session:** running the equivalent
  notebook-template fix on PROD, and checking whether prod's Postgres volume
  has the `stop_requested_at` migration applied. Do not touch prod-affecting
  infra outside an actual deployment session — standing instruction,
  unchanged.
- **SEPARATE, not gated, not started:** FLUX CUDA OOM on generate.
- **NEEDS HUMAN KAGGLE ACCESS, unverified:** the 5 stop/tracking hypotheses
  from the original 2026-07-05 investigation (see bottom section) — this
  environment cannot reach kaggle.com's kernel logs directly.

---

## Historical fixes already shipped

### 2026-07-05 — first supervisor/heartbeat pass (prod)

Three fixes shipped, in order:

1. `472a170` — `stop_requested_at` column + honest "couldn't confirm exit" /
   stale-`ready` detection in `get_session_status`. Made PAWN *honest* about
   not knowing a session's true state instead of falsely reporting `ended`.
2. `4c33bf8` — **supervisor daemon thread** in both warm-session notebooks
   (`image_flux_session`, `image_sdxl_session`): heartbeats for the kernel's
   whole life and `os._exit(0)`s the instant it sees a stop/expiry, so Stop
   can kill the kernel during *any* phase (not just `ready`). Plus backend
   warmup-death detection via stale heartbeat. Intended to make Stop
   *actually* stop the kernel and to detect mid-warmup death.

Root-cause finding that's solid and should NOT be re-litigated: the
warm-session notebooks' serve-loop + model-load cells were **byte-identical
since 06-30** (verified via `git show`), so none of this was a recent
regression — the stop-only-works-during-`ready` gap existed since W.1
(06-29). Kaggle has **no external "cancel kernel" API**; cooperative
self-exit is the only stop mechanism possible.

**Still broken after this pass (per user, 2026-07-05):** session stop /
tracking was still not fully working. Specifics weren't captured that
session — this fed directly into the "Stop/tracking hypotheses" section at
the bottom of this doc, still unresolved as of 2026-07-14.

### 2026-07-14 — local dev "session is not starting", FIXED (2 bugs)

1. **UI silently swallowed the start/extend/stop error.**
   `ImageGenerator.tsx`'s `handleHeaderStart/Extend/Stop` caught the API
   error and only `console.error`'d it — never called `setError`, so the
   header Start button just silently reset with no visible feedback. Fixed:
   all three handlers now call `setError(err.message)`. Commit `97173a4`.

2. **`POSTGREST_PUBLIC_URL` has been blank in dev since the D.3/D.4 Postgres
   migration — a real regression, not an always-existing limitation** (the
   old code comment claiming "same as it did under Supabase" was wrong and
   has been corrected). Before commit `9350664` (2026-07-03, Supabase ->
   self-hosted Postgres+PostgREST), `SUPABASE_URL` was a real public cloud
   endpoint reachable from anywhere including Kaggle, regardless of where
   the backend ran — so local warm-session testing worked with zero extra
   setup. Self-hosted PostgREST runs as a local-only Docker container with
   no public URL, so `start_session()` had 412'd for every local dev session
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
   shipped no migration for already-initialized Postgres volumes
   (`schema.sql` only runs via `docker-entrypoint-initdb.d` on a brand-new
   volume) — this dev machine's volume predates that column. Added
   `postgres/migrations/2026-07_image_sessions_stop_requested_at.sql` and
   applied it locally. **This same gap may exist in production** if prod's
   Postgres volume was also initialized before 2026-07-05 and this migration
   was never run there — check `\d image_sessions` on the prod DB before
   assuming Stop works there (this check is part of the deployment-gated
   work, see Status above). Commit `30d5825`.

Live-verified end-to-end against a real Kaggle kernel through the tunnel:
Start -> Warming -> job queued -> Stop -> Stopping -> honest "kernel didn't
confirm exit in time" after the 30s grace window (expected, kernel was still
installing deps). The full warm-session plumbing genuinely works locally.

**Same-day tunnel note (not a new bug):** the user flagged a fresh Kaggle
failure log the same day — real Kaggle log, `gaierror: Name or service not
known` resolving `channels-lap-because-tcp.trycloudflare.com` inside cell-1
(`patch_session({"status": "installing"})`). This is the exact dev tunnel
URL from the local-dev verification above, which was intentionally stopped
(`docker compose stop cloudflared`) once verification finished — quick
Cloudflare Tunnels don't persist their hostname across restarts, and
`docker-compose.override.yml` still pointed at the now-dead URL. Any new
local session-start attempt hits this until the tunnel is restarted and the
override file updated with the new URL (steps in
`docker-compose.override.yml.example`) — see §4 "Needs you" below. This is
also the exact class of failure the current active-work notebook hardening
(Step 4 below) targets: a `patch_session()` call that raises on a network
failure, killing the run before any heartbeat lands.

---

## Current root-cause diagnosis: "notebook auto-fails, app stuck on Warming forever"

**Symptom (user-reported):** a warm image session starts, the Kaggle
notebook stops abruptly, and PAWN keeps showing "Warming" — it never flips
to an error and never recovers, in both the original prod report and later
reproduced against dev.

**Two independent legs, both real** (confirmed by reading
`backend/app/core/image_session.py`, `backend/app/core/kaggle.py`, and both
warm-session notebook templates end to end):

1. **The backend has no independent signal that the kernel died.** All
   forward status transitions (`installing`→`loading_model`→`ready`) and
   every heartbeat are written *by the notebook* over PostgREST, never by
   the backend. If the notebook never lands a single heartbeat (PostgREST
   unreachable — dead tunnel `gaierror` as above; RLS token mismatch; writes
   silently rejected), `heartbeat_at` stays NULL and the only fallback was a
   **900s (15-min) wall-clock timeout** — the UI showed "Warming" that whole
   time. Yet `kaggle.py` *already has* working `/kernels/status` polling
   code on the cold path (`_wait_until_complete`) — it was just never used
   for warm sessions. This is the headline fix of the active work below.

2. **The notebook kills itself on transient failures and hides its own
   errors.** `patch_session()`/`patch_job()` are fire-and-forget (never
   check the response — a silently rejected write is invisible) yet **can
   raise** on network errors (no try/except):

   ```python
   def patch_session(fields):
       requests.patch(f"{REST}/image_sessions", headers=HEADERS,
                      params={"id": f"eq.{SESSION_ID}"}, json=fields, timeout=20)
       # no .raise_for_status(), no response check at all
   ```

   The live-observed failure was exactly this: `gaierror` raised out of
   cell-1's `patch_session({"status":"installing"})`, killing the run before
   the first heartbeat (see the tunnel note above). Concretely, this explains
   "not even informing the app": cell-2's failure handler (`except Exception
   as e: patch_session({"status": "error", ...}); raise`) *looks* like it
   reports failure honestly, but if that one `patch_session` call is itself
   silently rejected, the row never updates and Kaggle just tears the kernel
   down — the app stays stuck at whatever status it last successfully wrote.
   The supervisor thread's heartbeat write has the same blind spot, and is
   additionally gated behind a successful *read* first (`_supervisor()`:
   `if not _sess: continue` skips the heartbeat patch too when
   `get_session()` returns nothing) — a persistent read hiccup silently
   disables heartbeats entirely. Secondary gap: cell-1's `pip install` has
   **no try/except at all**, unlike cell-2's model-load — a `pip install`
   failure (version conflict, transient PyPI blip, Kaggle base-image drift)
   raises uncaught with zero report.

**Net: the notebooks' error-reporting design assumed every PostgREST write
succeeds, and nothing in the code could tell when that assumption was
false — and the backend had no independent way to check.** Both legs are
addressed by the active implementation plan below.

---

## Active implementation plan (CODE-COMPLETE — all 6 steps done; real-Kaggle live smoke test still needs the user)

Work lands on `dev`. Prod deploy is a separate later session — the
notebook-template changes only take effect on prod when redeployed there.

### Step 1 — `backend/app/core/kaggle.py`: public kernel-status probe — DONE
- `TERMINAL_KERNEL_STATUSES = frozenset(_DONE | _FAILED)` next to the
  existing sets.
- New `kernel_status(username, api_token, kernel_name) -> Optional[str]`:
  one best-effort `GET /kernels/status` via the existing `_client()` (same
  params shape as `_wait_until_complete`), returns Kaggle's lowercased
  status (`queued`/`running`/`complete`/`error`/`cancelled`/…) or **None on
  any failure — never raises** (None = "no information", callers fall back
  to current behavior).

### Step 2 — `backend/app/constants.py`: three new knobs — DONE
- `IMAGE_SESSION_KAGGLE_PROBE_INTERVAL_SECONDS = 30` (throttle vs the 3s
  frontend poll)
- `IMAGE_SESSION_STARTUP_PROBE_AFTER_SECONDS = 60` (don't probe brand-new
  sessions)
- `IMAGE_SESSION_RUNNING_NO_HEARTBEAT_TIMEOUT_SECONDS = 180` (Kaggle says
  "running" but zero heartbeats ever → rendezvous broken)
- **Kept `IMAGE_SESSION_STARTUP_TIMEOUT_SECONDS = 900`** — it's now only the
  backstop for when the probe returns None (no creds / Kaggle API down),
  exactly where conservatism is right (a long GPU queue legitimately delays
  the first heartbeat). When the probe says `queued`, the 900s flip is
  suppressed entirely.

### Step 3 — `backend/app/core/image_session.py`: probe integration — DONE
- **3a.** Module-level `_probe_cache: dict[str, tuple[float, Optional[str]]]`
  (session_id → (monotonic ts, status)) + helper
  `_kernel_probe(user_id, model, session_id)`: serves a cached result < 30s
  old; else `key_store.get_kaggle(user_id)` (None → skip probe), slug from
  `get_image_model(model).session_slug`, `kaggle.kernel_status(...)`; whole
  body wrapped try/except → None. Single-process uvicorn → in-process cache
  is fine; `get_session_status` already runs in a threadpool so the blocking
  HTTP call is safe.
- **3b.** Warmup branch rewritten, existing dead-reason strings preserved
  verbatim for the unchanged paths:
  1. Heartbeat stale > 90s → existing error (unchanged, no probe needed).
  2. Heartbeat present but past HALF the stale window (> 45s) → early probe
     check, so a confirmed-dead kernel doesn't wait out the rest of the 90s.
  3. No heartbeat yet, age > 60s → probe:
     - probe ∈ `TERMINAL_KERNEL_STATUSES` → error naming Kaggle's reported
       status, pointing at the kernel log on kaggle.com/code.
     - probe == `running` and age > 180s → error: kernel running but never
       reached PAWN's database (PostgREST rendezvous broken — tunnel down,
       RLS token mismatch, writes rejected).
     - probe != `queued` and age > 900s → existing backstop message
       (`queued` suppresses this entirely — a legitimate GPU-queue wait).
  4. On any flip: existing guarded UPDATE + `_probe_cache.pop(session_id)`.
  - `ready` branch NOT probed (3s heartbeats already give 90s detection);
    `stopping` branch NOT probed (documented follow-up, not urgent).
- **3c.** Added `created_at` to the status response dict (passed through
  as-is, same convention as `expires_at`) — the frontend elapsed timer
  (Step 5) needs it.
- **Tests:** 13 new/updated tests in `backend/tests/test_image_session.py`
  (autouse fixture clearing `_probe_cache` between tests — it's module-level
  state and most tests reuse session id `"s1"`; terminal-status early flip;
  `complete` also flips; `queued` stays warming AND suppresses the 900s
  backstop; `running` recent stays warming; `running` + no heartbeat past
  180s flips with the rendezvous message; no-creds skips the probe entirely
  — `kernel_status` never called; throttling — two calls within the window
  only hit Kaggle once; half-stale-heartbeat early check; response includes
  `created_at`) plus 5 new `kernel_status` unit tests in
  `backend/tests/test_generate.py` (mirrors the existing `_client`-mocking
  pattern used for `_wait_until_idle`/`deploy_kernel`). One existing test
  (`..._warmup_no_heartbeat_falls_back_to_timeout`) updated to explicitly
  mock the probe as unavailable, for determinism (avoids relying on a real,
  fast-failing localhost:5432 connection attempt). 76/76 green across both
  touched test files (`docker compose exec backend pytest
  tests/test_image_session.py tests/test_generate.py`), backend rebuilt.

### Step 4 — Notebook templates — DONE
(both `image_sdxl_session/` and `image_flux_session/notebook.ipynb`;
cell-0 code kept identical across the two)
- **4a. Cell-0:** replaced `patch_session`/`patch_job` with a shared
  `_rest_patch(...)` that never raises: try/except around the request,
  checks `status_code < 300`, one retry after `time.sleep(2)`, loud
  `[pawn] ...` `print(..., flush=True)` on final failure. Sends `Prefer:
  return=representation` and logs "matched 0 rows (RLS/session-token
  mismatch?)" when the response body is `[]` — makes the
  silently-rejected-write case observable in the Kaggle kernel log. Tracks
  `_last_rest_ok = time.time()` on any successful PostgREST contact (also
  in `get_session()`/`next_job()`).
- **4b. Cell-0 supervisor:** decoupled — the heartbeat patch fires every
  tick regardless of whether the read above succeeded (safe now that
  `patch_session` itself never raises). New self-exit:
  `_REST_UNREACHABLE_EXIT_SECONDS = 600` — no successful PostgREST contact
  in 600s → loud log, best-effort `patch_session({"status": "ended"})`,
  `os._exit(1)` (an unreachable kernel can never serve or be stopped from
  PAWN; exit 1 marks the Kaggle run failed, which the Step-3 probe then
  reports precisely instead of the kernel just vanishing with no trace).
- **4c. Cell-1:** wrapped the pip install in try/except →
  `patch_session({"status":"error", "error": f"dependency install failed:
  {e}"})` + `raise` (mirrors cell-2). The leading
  `patch_session({"status":"installing"})` can no longer raise per 4a —
  kills the exact live-observed `gaierror` failure.
- **4d. Cell-3:** wrapped loop-top `get_session()`/`next_job()` in
  try/except → log + `time.sleep(POLL); continue` so a transient blip can't
  kill a warm session mid-flight.
- Edit mechanics: a small Python script (json.load → replaced cell-0's body
  after the shared setup marker, cell-1's install block, cell-3's loop-top
  block → json.dump); every edit verified against BOTH templates via a
  dedicated pytest module (Step 6) rather than one-off manual checks —
  valid JSON, `__PAWN_PAYLOAD_B64__` present, every code cell `compile()`s
  clean, cell-0 bodies byte-identical between sdxl/flux. `git diff` reviewed
  line-by-line; no stray metadata/formatting churn.

### Step 5 — Frontend (small, visibility only) — DONE
- `frontend/src/api/client.ts`: `SessionStatus` gained
  `created_at?: string | null`.
- `frontend/src/components/ImageGenerator.tsx`: new `WARMUP_LABELS` map
  (starting/installing/loading_model → short labels) + `elapsed(createdAt)`
  helper (mirrors the existing `countdown()`). Warming pill now reads
  `Warming · {label} · {elapsed}`, reusing the existing 1s ticker (already
  running during warmup since `session.alive && session.expires_at` are
  both true then — no new effect needed). `tsc --noEmit` + `npm run build`
  both clean.

### Step 6 — Full gate + live verification — DONE (except the real-Kaggle smoke test)
- New `backend/tests/test_kaggle_session_templates.py` (9 tests, built from
  `IMAGE_MODELS`'s own `session_template` paths so it can't drift from the
  app's registry): valid JSON, `__PAWN_PAYLOAD_B64__` present, every code
  cell `compile()`s, exactly 4 cells, cell-0 bodies byte-identical across
  both templates, writes never go through a bare unhandled
  `requests.patch`, cell-1 wraps pip install, supervisor has the
  unreachable-self-exit. All 9 green.
- Full gate: `docker compose build backend && docker compose exec backend
  pytest -n auto` → **438/438 green** (up from 415 before this plan's work;
  run twice to rule out flakes, both clean), then `tsc --noEmit` + `npm run
  build` → clean.
- **Live-verified via Chrome against the real running dev stack** (mocked
  the `/generate/session/status` fetch response in the browser console —
  deliberately did NOT start a real Kaggle session, since that would spend
  the user's real GPU quota without asking first):
  - Warming state (`status: "loading_model"`, `created_at` 62s in the
    past): pill correctly rendered "Warming · loading model · 1m 21s",
    confirmed the elapsed time ticks upward live over the next several
    seconds ("1m 21s" → "1m 39s").
  - Probe-detected dead-kernel error (`status: "error"`, the exact message
    text `_kernel_probe`'s terminal-status branch produces): the amber
    warning box rendered the precise reason verbatim, and the pill
    correctly fell back to the idle Start-button state (not stuck showing
    "Warming").
  - **Still needs the user, not done this session:** a live smoke test
    against a REAL Kaggle kernel (start a session, verify "Warming ·
    installing deps · 1m 23s"-style progression to ready; separately, kill
    the tunnel/PostgREST reachability and confirm PAWN flips to a precise
    error within ~90s instead of 15 minutes) and checking the Kaggle kernel
    log itself for the new `[pawn]` lines — this needs real Kaggle creds
    and a restarted `cloudflared` tunnel (`docker compose --profile tunnel
    up -d cloudflared`, update `docker-compose.override.yml`), neither of
    which this environment has. This is the one item from the original
    diagnosis's "confirm against a real kernel log" ask that remains open.

### Out of scope for this plan
- FLUX CUDA OOM (separate, see below).
- Prod deploy + prod's `stop_requested_at` migration check (deploy-session
  step, per the standing instruction).
- Probing the `stopping` branch (documented follow-up).
- Per-session PostgREST JWT auth (unrelated, longstanding deferred item).

### Doc updates on completion
This file (mark fully DONE), `build_tracker.md` Image Lab section,
`current_state.md`, `dev_log.md`.

---

## Separate, also-outstanding: FLUX CUDA OOM on generate — FIX RE-APPLIED 2026-07-14

`device_map="balanced"` packs GPU 0 to the brim on model load, then OOMs on
the next inference call. A `max_memory` cap fix was drafted (`84c0a4d`) then
reverted (`d96c1c6`) — the revert message says "pausing further FLUX
iteration for now," not that the fix was disproven; it was simply never
verified against real Kaggle hardware before being backed out.

**Re-applied the same fix**, unchanged in substance, to both FLUX templates
(`image_flux/notebook.ipynb` — cold job, and `image_flux_session/notebook.ipynb`
— warm session), cell 2's `FluxPipeline.from_pretrained(..., device_map="balanced")`
call: added `max_memory={0: "13GiB", 1: "13GiB"}` so accelerate's balanced
dispatcher is forced to leave ~1.5GiB headroom on each T4 for inference-time
activations instead of packing weights to the ~14.56GiB edge (the observed
failure: GPU 0 loaded to 12.95/14.56GiB, OOMed on the very next `pipe(...)`
call even though the model itself loaded fine). Also added
`local_files_only=True` to both `from_pretrained` calls (the balanced path
and the CPU-offload fallback) — SDXL's templates already set this; FLUX's
never did, meaning every session start paid for an unnecessary Hub
round-trip to check the repo's config/revision even though the weights are
already mounted locally.

Confirmed this is still the current, unpatched state of both templates
before applying (the revert in `d96c1c6` was never re-touched by any later
notebook work, including the 2026-07-14 dead-session-detection pass — that
pass only edited cell 0/1/3, never cell 2's model-load call). The
warm-session serve loop (cell 3) already wraps each job's `pipe(...)` call
in its own try/except, so a CUDA OOM was never crashing the kernel — it was
silently failing every single generate job with an `error` status forever,
since GPU 0 stayed packed to the brim for the session's whole lifetime.

Verified: both notebooks re-validated as well-formed JSON, every code cell
still `compile()`s clean, `test_kaggle_session_templates.py` doesn't assert
on this cell's exact source so no test changes needed, full backend suite
(438 tests) green. **Not independently verified on real Kaggle hardware —
still needs a live FLUX warm-session generate to confirm the OOM is
actually gone** (no Kaggle access from this session; blocked on the same
local-network issue as the rest of Image Lab local testing this round).
Prefer SDXL when isolating unrelated session-lifecycle issues until this is
live-confirmed.

---

## Stop/tracking hypotheses — still needing human Kaggle access (unverified since 2026-07-05)

Specifics were never captured for the "still broken" report above — the
next live-debugging session should get concrete repro details first:
which model (SDXL vs FLUX — FLUX also OOMs, confounding testing); at which
phase Stop was clicked; what the UI showed vs. what kaggle.com showed; was
it a fresh session started *after* the `4c33bf8` supervisor deploy (a kernel
predating that deploy will never self-stop — expected, must be ruled out
first); and the exact `image_sessions` row (status, heartbeat_at,
stop_requested_at, expires_at) alongside the kaggle.com kernel state at the
same moment.

1. **Is the supervisor thread actually running on the deployed kernel?**
   Verify a *fresh* post-`4c33bf8` session's kernel logs show the supervisor
   started. If a running kernel predates the deploy, that fully explains
   "still broken."
2. **RLS token on reads.** The supervisor reads `get_session()` via
   PostgREST with `X-Session-Token`. If the token GUC / RLS ever fails to
   match, reads return `[]` → supervisor treats as transient (continues), so
   it would NEVER see the stop and never exit. Confirm reads return the row
   for a live session (heartbeats landing proves *writes* work, but check
   reads explicitly).
3. **`os._exit(0)` inside a Kaggle kernel** — confirm it actually terminates
   the Kaggle *run* (frees the GPU) and isn't caught/restarted by Kaggle's
   harness. This is the load-bearing assumption of the whole fix and is
   UNVERIFIED on real hardware (no Kaggle access from the dev/agent
   environment).
4. **Frontend caching** — confirm the user is on the freshly-built bundle,
   not a cached older `ImageGenerator.tsx` that ignores the `error` status.
5. **Orphaned / multiple kernels** — redeploys + OOM retries may have left
   several kernel versions running on the same slug (`pawn-flux-session` /
   `pawn-sdxl-session`), only one of which is bound to the session row PAWN
   is stopping. The others keep running invisibly. Check kaggle.com for
   stray runs.

**Verification bar before calling any of this done:**
- A *fresh* session, Stop clicked during `loading_model`, → kaggle.com shows
  the run actually ended within ~seconds (GPU freed), AND PAWN UI reflects
  it.
- A kernel killed from kaggle.com → PAWN flips to an `error` banner within
  the heartbeat-stale window.
- Both must be reproduced live (no Kaggle access from the agent
  environment, so this is a human-in-the-loop verification).

## Needs you, not code

- **Restart the local dev Kaggle tunnel** before any further local Image Lab
  testing — `docker compose --profile tunnel up -d cloudflared`, then update
  `docker-compose.override.yml` with the freshly-printed
  `https://*.trycloudflare.com` URL (quick Cloudflare Tunnels don't persist
  their hostname across restarts). Steps are in
  `docker-compose.override.yml.example`.
- **Delete the orphaned `pawn-image-flux-1-schnell` Kaggle kernel** — a
  stray notebook from an old mismatched FLUX title, unused since the
  slug-derived title fix. Safe to delete manually; needs your own Kaggle
  account access (BYOK credentials aren't reachable/decryptable from
  outside the running app).
