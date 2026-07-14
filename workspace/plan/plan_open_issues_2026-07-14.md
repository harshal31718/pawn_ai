# Plan: Open Issues & Improvements (post Phase A/M/N/O/P audit)

*Branch: dev. Status: NOT STARTED — planning only.*
*Written 2026-07-14 after auditing `build_tracker.md`, `current_state.md`,
`dev_log.md`, `workspace/implemented_phases/gap_audit_2026-07-14.md`, and
`workspace/plan/plan_imagelab_session_issues.md`, then cross-checked each
claim against actual git history (`git log`) and the current source tree —
several items the docs still describe as "open" turned out to already be
fixed in commits the docs weren't updated for (A.9-7's `chat_complete`
failover events, the full `pytest -n auto` gate). Those are excluded below.
Everything listed here was independently re-verified as still true in the
current codebase, not just copied from a stale doc.*
*Tracker: not yet registered as a lettered phase in `build_tracker.md` —
register the ones the user picks to act on.*

---

## 0. How to read this

Four groups, roughly in priority order:

- **§1 Image Lab — production notebook fix.** The one item the user
  explicitly asked to include. Highest-impact, but gated: don't start until
  an actual deployment/prod-access session (per your standing instruction
  not to touch prod-affecting code otherwise).
- **§2 Backend/agent correctness gaps.** Real bugs or missing features found
  during Phase A/O work, deferred at the time, still unfixed.
- **§3 Small cleanups.** Low-severity, low-risk, no user-facing behavior
  change — good filler between bigger items.
- **§4 Needs you, not code.** Manual steps only you can do (Kaggle/Drive
  account access, confirming a fix live). Not implementation work.

---

## 1. Image Lab — production notebook fix (gated, needs a deployment session)

Full diagnosis already lives in `workspace/plan/plan_imagelab_session_issues.md`
(2026-07-14 section) — this is a summary + the concrete fix plan, not a
re-diagnosis.

**Symptom (user-reported):** in production, a Kaggle warm-session notebook
sometimes auto-fails and Kaggle tears the kernel down, but PAWN's UI stays
stuck showing "warming" — the app never finds out the session died.

**Root cause (code-verified, not yet confirmed against a real Kaggle log):**
both warm-session notebook templates
(`backend/app/kaggle_templates/image_{flux,sdxl}_session/notebook.ipynb`)
have read functions (`get_session()`, `next_job()`) that call
`r.raise_for_status()`, but the *write* functions (`patch_session()`,
`patch_job()`) don't check the response at all — every status/heartbeat/error
write to PostgREST is fire-and-forget. If PostgREST ever rejects a write (RLS
`session_token` mismatch, a schema-drift gap like the `stop_requested_at` one
found this session, a transient 5xx), the notebook has no way of knowing —
nothing retries, nothing surfaces it. Concretely: cell-2's failure handler
(`except Exception as e: patch_session({"status": "error", ...}); raise`)
*looks* like it reports failure honestly, but if that one `patch_session`
call is itself silently rejected, the row never updates and Kaggle just
tears the kernel down — exactly "stuck on warming, PAWN never finds out."
The supervisor thread's heartbeat write has the same blind spot, and is
additionally skipped whenever a *read* fails first, so a persistent read
hiccup silently disables heartbeats too, forcing the 900s wall-clock
dead-session fallback instead of the 90s heartbeat-staleness check.

**Fix plan:**
1. Add `.raise_for_status()` (or log + retry-once) to `patch_session()` and
   `patch_job()` in both `image_flux_session/notebook.ipynb` and
   `image_sdxl_session/notebook.ipynb`.
2. Decouple the supervisor's heartbeat write from a successful read —
   currently `_supervisor()` does `if not _sess: continue`, skipping the
   heartbeat patch whenever `get_session()` returns nothing, even on a
   transient hiccup.
3. Wrap cell-1's `pip install` in a try/except that reports failure the same
   way cell-2 does — right now a `pip install` failure (version conflict,
   transient PyPI blip, Kaggle base-image drift) raises uncaught with zero
   report, relying entirely on the same blind fallback.
4. Before assuming this is the full story: check prod's Kaggle kernel log for
   the actual last-printed line before a real failure, and cross-check
   `image_sessions`' last successfully-written status/`heartbeat_at` against
   that timestamp — confirms a write was silently dropped rather than
   something else (e.g. a genuine OOM that also killed the write attempt,
   which this fix wouldn't help with — see the separate FLUX OOM item below).
5. **Check whether prod's Postgres volume has the `stop_requested_at` column**
   at all — `postgres/migrations/2026-07_image_sessions_stop_requested_at.sql`
   was applied locally 2026-07-14 but prod's volume predates that commit
   (`472a170`, 2026-07-05) and may never have gotten it. Run
   `\d image_sessions` on the prod DB before assuming Stop works there.

**Gate:** don't touch the notebook templates or run prod migrations outside
an actual deployment session — same standing instruction as before. When
that session happens, this is ready to execute directly from steps 1-5 above.

### 1a. Also open in Image Lab, lower priority, not gated

- **FLUX CUDA OOM on generate** — `device_map="balanced"` packs GPU 0 to the
  brim on model load, then OOMs on the next inference call. A `max_memory`
  cap fix was drafted (`84c0a4d`) then reverted (`d96c1c6`) — still unfixed.
  Confounds FLUX-specific stop/session testing; prefer SDXL when isolating
  unrelated session-lifecycle issues.
- **Stop/tracking hypotheses #3-5, unverified** (from the original
  2026-07-05 investigation, still listed in
  `plan_imagelab_session_issues.md`): is the supervisor thread actually
  running on the deployed kernel (vs. a pre-fix kernel still live)? Does a
  PostgREST read failure ever cause the supervisor to miss a stop signal
  entirely? Does `os._exit(0)` inside a Kaggle kernel actually free the GPU,
  not just end the visible run? Are there orphaned/multiple kernel versions
  on the same Kaggle slug from earlier redeploys? All four need Kaggle log
  access this environment doesn't have — human-in-the-loop only.

---

## 2. Backend/agent correctness gaps

### 2.1 — Mid-loop answer + closing synthesis can both fire, producing two answers

**Found:** during O.3 live verification (2026-07-14), a heavy/research turn
where the mid-loop model had already streamed a complete answer (after a
calculator tool call) still went through the mandatory closing synthesis,
which independently re-answered the same question — producing two
similar-but-differently-worded answers in one message. Documented under O.1
in `workspace/implemented_phases/plan_reply_quality.md` with a fix sketch;
confirmed via `git log` that no later commit addressed it — still open.

**Fix sketch (from that doc):** detect when the execute loop's own last
assistant turn already reads as a complete answer (no trailing
tool-call-seeking phrasing, sufficient length) and skip the closing synthesis
in that case; or restructure so mid-loop text before the designated final
step is never itself streamed/treated as answer-shaped (suppress its live
streaming, always route the actual reply through one designated synthesis
step). Needs its own investigation before picking an approach — not a
one-line fix.

**Files:** `backend/app/agent/graph.py` (`execute_node`, the
plan → execute → final flow).

### 2.2 — Duplicate "PAWN" Drive root folders (pre-existing, from before the concurrency fix)

Not purely a "needs you" item — flagging here because it may still be
actively causing scope-resolution confusion. `core/drive_factory`'s
concurrent-cache-miss race (fixed 2026-07-13, commit `2146b07`) means any
user who hit that race *before* the fix has two "PAWN" root folders in their
Drive, and code that walks `chats/`/`projects/` under "the" root may resolve
against whichever one it finds first — silently missing content that lives
under the other root. `gap_audit_2026-07-14.md` flagged this as the
lead suspect for one mis-scoping incident during M.7 testing (later
correctly attributed to a different bug — a stale closure sending the wrong
chat ID — but the duplicate-root risk itself was never ruled out or fixed,
just not the cause *that specific time*). The merge itself has to be manual
(§4) but it's worth actually doing before it causes a real, harder-to-debug
incident, not just a theoretical one.

---

## 3. Small cleanups (low risk, low priority — good filler)

- **`EndpointEntry.secret` vestigial field** (`backend/app/registry/schemas.py`) —
  a required `str` field, populated in `registry/seed.py`'s `INITIAL_MODELS`/
  `INITIAL_ENDPOINTS` and in the live `data/registry/endpoints.json`, never
  read anywhere in the app (`Resolver`/`_resolve_key()` only ever use
  `key_store.get_key(user_id, provider)` — the per-user BYOK key). Confirmed
  still present. Removing it touches a live data file, not just code — do
  it deliberately, not as a drive-by.
- **`conversations_drive.py`'s broad `except (json.JSONDecodeError, Exception): pass`**
  pattern (several call sites) swallows *any* error, not just parse failures.
  `routes/memory.py`'s 404 resolution for unknown scopes relies on this
  behavior, so a transient Drive error currently looks identical to "scope
  not found" — misleading if it ever actually happens. Deferred from M.6
  code review as low-severity; confirmed still present.
- **`routes/memory.py`'s `_delete_scope_chunks`** has no try/except, unlike
  the sibling `_delete_chunks` pattern in `conversations.py` for the same
  class of derived-index cleanup. Confirmed still missing. Low severity — a
  rebuildable index (`POST /memory/rebuild` already exists), not user data
  loss, but inconsistent with the established pattern elsewhere.

---

## 4. Needs you, not code

- **Merge the duplicate "PAWN" Drive root folders** (see §2.2) — not safely
  automatable (risk of picking the wrong folder to delete/merge content
  into). Needs manual inspection in Drive.
- **Restart the local dev Kaggle tunnel** before any further local Image Lab
  testing — `docker compose --profile tunnel up -d cloudflared`, then update
  `docker-compose.override.yml` with the freshly-printed
  `https://*.trycloudflare.com` URL (quick Cloudflare Tunnels don't persist
  their hostname across restarts). Steps are in
  `docker-compose.override.yml.example`.
- **Delete the orphaned `pawn-image-flux-1-schnell` Kaggle kernel** — a stray
  notebook from an old mismatched FLUX title, unused since the slug-derived
  title fix. Safe to delete manually; needs your own Kaggle account access
  (BYOK credentials aren't reachable/decryptable from outside the running
  app).

---

## 5. Explicitly excluded (verified already fixed, despite what some docs still say)

Caught these while cross-checking `current_state.md`/`gap_audit_2026-07-14.md`
against real git history — the docs hadn't been updated after the fix
landed, so listing here to prevent re-work:

- **A.9-7 (`normalize.chat_complete` missing `on_provider_switch`)** — fixed
  in commit `d3dec49` ("chat_complete failover events (A.9-7)"),
  2026-07-14, *before* the round-1/round-2 bugfix sessions.
  `current_state.md`'s 2026-07-13 audit entry describing it as "flagged for
  later" is stale.
- **Full `pytest -n auto` gate (16 SQLite-checkpointer-contention failures)** —
  fixed across `ea765df` → `8a098e3` → `c5a62db`, closed and documented in
  `7837e09` ("docs: record pytest gate closure"). `current_state.md`'s
  round-2 entry saying "still needs the user to re-run" predates that
  closure.
- **A.9 (8-item) / M.7 (7-item) live-verification checklists** — both fully
  confirmed live via `claude-in-chrome` 2026-07-14, per `build_tracker.md`'s
  top summary and `gap_audit_2026-07-14.md` §J/§K/§L.

---

## 6. Suggested sequencing

Independent items — pick any order, but if doing several in one session:

1. §3 cleanups first — smallest, safest, no live-behavior change, good
   warm-up.
2. §2.1 (mid-loop double-answer) next — needs real investigation/design
   before coding, highest user-visible payoff of the code-only items.
3. §1 (Image Lab prod fix) only once an actual deployment session is
   underway — don't start early per the standing instruction.
4. §4 items whenever convenient — hand off to you directly, no coding
   required from this end.
