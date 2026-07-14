# Plan: Open Issues & Improvements (post Phase A/M/N/O/P audit)

*Branch: dev. Status: IN PROGRESS — §2.1 (O.1 mid-loop double-answer) and
§2.2's code part (deterministic Drive root resolution) DONE 2026-07-14,
both committed and tested. §2.2's actual folder merge stays a manual,
user-only step (unchanged — see §2.2/§4). Everything else still NOT
STARTED.*
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

### 2.1 — Mid-loop answer + closing synthesis can both fire, producing two answers — DONE 2026-07-14

**Found:** during O.3 live verification (2026-07-14), a heavy/research turn
where the mid-loop model had already streamed a complete answer (after a
calculator tool call) still went through the mandatory closing synthesis,
which independently re-answered the same question — producing two
similar-but-differently-worded answers in one message. Documented under O.1
in `workspace/implemented_phases/plan_reply_quality.md` with a fix sketch.

**Fix applied (chose the "restructure" branch of the original sketch):**
`execute_node`'s tool loop now defers (buffers, never dispatches as `token`
events) every iteration's content on heavy turns via a new
`defer_loop_content` flag, instead of streaming it live as before. If a
further tool call follows in the same iteration, the buffered text is
flushed as one chunk right before that tool's `step` event — preserving
Phase N's "thinking before a tool call" interleaving, just as a single flash
instead of token-by-token. If the iteration cleanly stops with no more
tool_calls, the buffered content is discarded entirely — the mandatory
closing synthesis becomes the sole, authoritative, user-visible answer for
heavy turns, exactly as O.1 always intended. Light (but agentic) turns are
completely unaffected (`defer_loop_content` is heavy-only) — their own
clean-stop content remains the real, final, live-streamed answer, since they
have no mandatory closing call to conflict with.

The rejected alternative (heuristically detecting "already a complete
answer" and skipping the closing synthesis) was not used — it would have
reintroduced the original O.1 regression (a cheap orchestrator model's own
text serving as the final answer for a heavy/deep-research turn) and relies
on a fragile heuristic ("no trailing tool-call-seeking phrasing, sufficient
length").

**Side effect (net positive, not just neutral):** since heavy-turn loop
iterations no longer dispatch content live, a mid-stream failure during one
of them is now always safe to fall through to a fresh closing-synthesis
attempt (nothing was shown to the user yet), rather than hard-failing the
whole turn — more resilient than before, not just bug-neutral. The "once a
token has reached the user this call, a failure must propagate" contract
still holds, but now applies to the closing-synthesis call itself (the only
place content reaches the user directly on a heavy turn) instead of the
loop's own iterations.

**Tests:** `backend/tests/test_agent.py` — 5 existing tests updated to
assert the fixed behavior (`test_execute_node_heavy_pure_text_stream_still_gets_closing_synthesis`,
`test_execute_node_streams_text_before_a_tool_call_and_final_synthesis_after`
[renamed], `test_execute_node_multi_tool_call_sequence`,
`test_execute_node_buffers_closing_synthesis_when_research_tools_used`,
`test_execute_node_streams_live_when_no_research_tools_used`); 1 test
recontextualized to light difficulty (`test_execute_node_light_loop_failure_after_content_sent_propagates_not_falls_through`,
renamed from a heavy-turn variant that no longer applies); 2 new tests added
(`test_execute_node_heavy_loop_failure_after_content_buffered_falls_through_to_closing_call`,
`test_execute_node_heavy_closing_synthesis_failure_after_content_sent_propagates`).
409 backend tests green (`docker compose exec backend pytest -n auto`, run
twice to rule out flake — one unrelated single-run SQLite/xdist lock flake
seen once, gone on retry, matches the known pre-existing xdist-on-Windows
issue, not caused by this change).

**Live-verified** against the real running dev stack: "Analyze this: use the
calculator tool to compute 340 divided by 8, then explain in one short
sentence what that result could represent in everyday life" (heavy via the
"Analyze" keyword trigger, no research tools so streams live, not buffered
by O.3) → exactly one tool call (calculator) → exactly one answer dispatched
("Dividing a $340 bill among eight friends means each person would pay
$42.50.") — no leaked/duplicate mid-loop text anywhere in the expanded
trace. Also incidentally observed, via an earlier (accidentally interrupted)
test on a research-gated prompt: a full verify-reject-revise cycle (with an
extra calculator call) produced zero stray answer text anywhere in the
persisted trace before the final verified draft — consistent with the fix.

**Files:** `backend/app/agent/graph.py` (`execute_node`'s tool loop),
`backend/tests/test_agent.py`.

### 2.2 — Duplicate "PAWN" Drive root folders (pre-existing, from before the concurrency fix) — CODE PART DONE 2026-07-14

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
just not the cause *that specific time*).

**Fixed (the safely-automatable part):** `storage/drive.py`'s
`get_or_create_root()` queried Drive's `files.list` with no `orderBy` and
`pageSize=1` — without an explicit order, Drive gives no guarantee of stable
ordering, so which "PAWN" folder got picked (when more than one exists)
could genuinely differ between calls/instances, not just be "whichever
happens to be found first" once and stay that way. Fixed: now queries
`orderBy="createdTime"` with `pageSize=10`, always resolving to the OLDEST
matching folder — deterministic across every call and every DriveStorage
instance (a real, previously-missing guarantee, not just a symptom
workaround), and favors the folder most likely to hold the most existing
history. When more than one folder is found, logs a clear stderr warning
(user ID + every folder ID + a pointer back to this doc) so the condition is
visible in logs instead of silently invisible, without touching any data.
6 new tests in `backend/tests/test_drive_storage.py` (new file — DriveStorage
itself had zero direct unit coverage before this; `_build_service` mocked to
avoid real Google API calls). 415 backend tests green (up from 409).

**Still needs you (unchanged, this part is NOT automated and shouldn't be):**
actually merging the two real "PAWN" folders' *contents* in your live Google
Drive account — moving/reconciling files between them requires judgment
about conflicts (e.g. two chats with colliding auto-generated titles, like
the false-alarm case `gap_audit_2026-07-14.md` §K already found) that isn't
safe to automate blindly. The code fix above means the app will now, at
least, *consistently* use the same (oldest, most-complete) root every time
instead of possibly flip-flopping — so the visible symptom should already be
far less confusing even before you get to the manual merge. See §4.

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
