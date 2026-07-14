# Plan: Open Issues & Improvements (post Phase A/M/N/O/P audit)

*Branch: dev. Status: §2.1 (O.1 mid-loop double-answer), §2.2's code part
(deterministic Drive root resolution), and §3 (all three small cleanups)
all DONE 2026-07-14, committed and tested. §2.2's actual folder merge stays
a manual, user-only step (unchanged — see §2.2/§4). §1 (Image Lab prod fix)
stays gated until a deployment session. §4 items are handed to the user
directly, no code involved.*
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

## 1. Image Lab — production notebook fix

§1 has moved to `workspace/plan/plan_imagelab_session_issues.md` — see that
file for the full diagnosis and implementation plan (IN PROGRESS as of
2026-07-14: Steps 1-3 of 6 done, live-verification and prod deployment
still pending). Kept here as a pointer only so this doc's numbering/history
stays intact; §2/§3/§4 below are unrelated and unaffected.

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

## 3. Small cleanups (low risk, low priority — good filler) — DONE 2026-07-14

- **`EndpointEntry.secret` vestigial field** (`backend/app/registry/schemas.py`) —
  a required `str` field, populated in `registry/seed.py`'s `INITIAL_MODELS`/
  `INITIAL_ENDPOINTS` and in the live `data/registry/endpoints.json`, never
  read anywhere in the app (`Resolver`/`_resolve_key()` only ever use
  `key_store.get_key(user_id, provider)` — the per-user BYOK key).
  **Removed** from `schemas.py`'s `EndpointEntry` model, `seed.py`'s
  `INITIAL_ENDPOINTS` (15 entries), the live `data/registry/endpoints.json`
  (18 entries), and `tests/test_rate_limiter.py`'s 6 `EndpointEntry(...)`
  constructions — no drive-by, all four sites cleaned together in one pass
  as the plan called for. JSON/Python syntax validated after the edit;
  backend rebuilt and confirmed booting clean (`Application startup
  complete`, registry loads without a validation error); live-verified via
  the model switcher UI (per-model provider lists render correctly, proving
  `GET /registry/models`, which reads `EndpointEntry.provider`, still works).
- **`conversations_drive.py`'s broad `except (json.JSONDecodeError, Exception): pass`**
  pattern (5 call sites) swallows *any* error, not just parse failures.
  `routes/memory.py`'s 404 resolution for unknown scopes relies on this
  behavior, so a transient Drive error currently looks identical to "scope
  not found" — misleading if it ever actually happens. **Fixed the
  visibility gap without changing behavior:** kept the broad catch (still
  correctly needed — Drive API errors must be caught here too, not just
  JSON errors) but simplified the redundant `(json.JSONDecodeError,
  Exception)` tuple to plain `Exception` (the former was misleading, since
  `Exception` alone already subsumes `JSONDecodeError`) and added a
  `print(..., file=sys.stderr)` at every site naming the function, the
  conv_id, and the actual exception, before falling through to the existing
  return/pass — so a real failure is now visible in logs instead of
  completely silent, with zero change to control flow or return values (all
  existing call-site contracts, including memory.py's 404-on-not-found
  behavior, are unchanged on purpose).
- **`routes/memory.py`'s `_delete_scope_chunks`** had no try/except, unlike
  the sibling `_delete_chunks` pattern in `conversations.py` for the same
  class of derived-index cleanup. **Fixed** by applying that exact sibling
  pattern: wrapped the delete in try/except, logs to stderr on failure
  (naming scope_type/scope_id + the exception) instead of raising — matches
  `_delete_chunks`'s own doc comment reasoning verbatim (best-effort,
  `memory_chunks` is a derived/rebuildable index, and by the time this runs
  `clear_memory`'s Drive-side work has already succeeded so there's nothing
  left to roll back on a Postgres failure here).

All three verified together: 415 backend tests green (no new tests needed —
these are pure logging/hygiene changes with no new observable behavior to
assert on, consistent with `_delete_chunks`'s own sibling having no
dedicated test either), backend rebuilt and confirmed booting clean.

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
