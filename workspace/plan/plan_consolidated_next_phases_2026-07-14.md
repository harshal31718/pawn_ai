# Consolidated Plan — Phases N, O, P, and Image Lab (post-gap-audit)

*Drafted 2026-07-14. Merges four in-flight threads into one sequenced backlog so
work can proceed phase by phase with a pause/test gate after each. Source docs
for full detail on N/O/ImageLab are kept as-is and linked below — this file
adds the sequencing decision, the working-tree status check, and the new
Phase P (UI polish) spec, which had no prior document.*

Status legend: `[ ]` not started · `[~]` in progress / partially done · `[x]` done & verified

---

## 0. Where things actually stand right now (verified via `git diff` + code read, not assumed)

The working tree has **substantial uncommitted code** from earlier local
Claude Code CLI sessions, referenced but not detailed in
`plan_interleaved_agent_streaming.md`'s commit message ("implementation
handed to local Claude Code CLI"). Checked file-by-file before writing this
plan so the sequencing below reflects reality, not the source docs' own
"not yet built" headers (which are now stale for Phase N):

| Item | Status found | Evidence |
|---|---|---|
| Phase N — `stream_chat_with_tools`/`chat_stream_with_tools` | **Code-complete** | `llm_core.py`/`normalize.py` have the new functions; `graph.py`'s `final_node` is gone, `execute_node` absorbed it; frontend `types.ts`/`Message.tsx`/`TraceView.tsx`/`ChatPage.tsx`/`useConversationStore.ts` all diff toward `segments`. Tests rewritten (`test_agent.py` etc.) + new `test_stream_with_tools.py`. |
| Phase N — live verification | **Not done** | Plan's own §6 says this needs a real provider + the user's machine; no evidence in `dev_log.md` that it ran. |
| Phase O — Appendix A registry re-tiering | **Partially done** | `models.json`/`endpoints.json` diff shows `llama-3.3-70b` moved `balanced→fast`, `glm-4.7` moved `fast→research`, two new `active:false` model stubs added — matches Appendix A.2/A.3 exactly. |
| Phase O — Appendix A.4 gotcha #1 (flip `ROLE_LEVELS["orchestrator"]`) | **Not done** | `constants.py` has zero diff; `orchestrator` is still `"fast"`. The plan explicitly flagged this as a required companion change — it's a loose end sitting in the tree right now, not yet a bug because `"fast"` still has 2 active tool-capable models (`gemini-2.5-flash-lite`, `llama-3.3-70b`), just weaker than intended. |
| Phase O.1–O.4 (the actual reply-quality fixes) | **Not started** | No `final_heavy`/`resolve_final_model` call from `execute_node`, no `WEB_SEARCH_FETCH_TOP_N`, no verifier node anywhere in `graph.py`/`constants.py`/`web_search.py`. |
| gap_audit_2026-07-14.md (A.9/M.7 live checklists) | **Done this session** | Both marked `[x]` in `build_tracker.md`; full record in the gap-audit file itself, §§F/J/K/L. Two small residual watch-items left there (router recall-keyword gap, one unreproduced console error) — not blocking, carried forward as backlog, not a new phase. |
| Image Lab warm-session stop/tracking | **Paused, needs live repro** | `plan_imagelab_session_issues.md` — three fixes shipped 2026-07-05, user reports still broken, next step is gathering concrete repro details (which the plan lists), not more blind code changes. |
| New UI requests (this session) | **Not started, no doc existed** | Four asks: trace/agent-message collapse+toggle, kebab-menu consolidation, search relocation+scope, project-page restructure. Speced fresh in §5 below. |

**First implication:** before building anything else, Phase N's uncommitted
diff needs to be *tested and committed* (or fixed and committed) — Phase O,
Phase P's trace-toggle work, and the orchestrator-tier loose end all sit on
top of it. Nothing else should be built on an unverified, uncommitted
foundation.

---

## 1. Sequencing decision

Recommended order (dependency-driven, cheapest/highest-impact first within
that constraint) — **confirm or reorder before I start**:

1. **N-verify** — confirm Phase N's existing implementation actually works, fix what doesn't, commit.
2. **O.1** — small diff, reverses a known live regression (the green-hydrogen benchmark failure), includes the missed orchestrator-tier flip.
3. **P** — the four UI requests from this session. Independent of O.2–O.4; P.1 (trace toggle) builds directly on N's now-verified `segments` model, so it's cheap to do right after N.
4. **O.2 → O.3 → O.4** — the deeper reply-quality work (fetch+extract, verifier, decomposition), per the source plan's own sequencing rationale.
5. **Image Lab** — independent of everything above; resumes whenever the user can do the live Kaggle-side repro steps the plan asks for. Not blocked by 1–4 and not blocking them either — can be picked up in parallel if the user wants to drive it themselves while I work on 1–4.

If you'd rather see the UI changes land before touching backend reply
quality (or vice versa), say so — 2 and 3 don't depend on each other and can
swap.

---

## 2. Phase N-verify — confirm & land the interleaved-streaming diff

*Full design already in `plan_interleaved_agent_streaming.md` — this is a
verify-and-commit pass, not a redesign.*

1. Run `docker compose exec backend pytest -n auto` against the current
   uncommitted diff — confirm the rewritten `test_agent.py` and new
   `test_stream_with_tools.py` actually pass (never confirmed in this repo
   per `dev_log.md`).
2. Run `tsc -b` + `vite build` on the frontend diff.
3. **Live check (needs the user + real BYOK keys):** send a tool-using
   message and confirm text genuinely streams before/around the tool card,
   not only after — the one thing the plan flags as unverifiable from a
   sandbox. This session's browser access makes it possible to actually do
   this now — I can drive it via Chrome and watch the live rendering.
4. Fix anything broken; commit as one change (or a couple of small ones) once green.

**Gate:** full backend suite green, frontend build clean, live streaming-with-tools confirmed working in the browser.

---

## 3. Phase O.1 — restore the synthesis quality floor

*Full design in `plan_reply_quality.md` §4 O.1 — this section just calls out what's left after the partial Appendix-A work already in the tree.*

1. Flip `ROLE_LEVELS["orchestrator"]` → `"balanced"` in `constants.py` (the missed Appendix A.4 companion change) so tool-driving still gets `gpt-oss-120b`-class models now that `glm-4.7` moved to `research`.
2. Re-wire `execute_node`'s close-out to call `resolve_final_model` (already exists in `router.py`, currently dead code) and do the final `stream_iteration(use_tools=False)` on `ROLE_LEVELS["final_heavy"]="research"` instead of the orchestrator model — the actual O.1-a fix.
3. Add the ordered fallback chain for `final_heavy` and the trace warning when synthesis is forced below the research tier.
4. Tests: synthesis picks the research tier at close-out; failover-below-floor emits the trace warning.

**Gate:** backend suite green; re-run the green-hydrogen benchmark prompt as a live regression check per the source plan's §6 — this alone may meaningfully improve the reply-quality complaint that started Phase O.

---

## 4. Phase P — UI polish (new this session, no prior doc)

Four independent-ish UI requests gathered during this session's live-testing
pass. P.1 depends on Phase N's `segments` model being verified (§2); P.2–P.4
have no backend dependency and could be done in any order or even before N
if you want the UI wins sooner — flag if so.

### P.1 — Two-level collapsible trace / agent-activity toggle

**Request (verbatim intent):** agent activity (plan, tool calls, provider
switches, delegated-subagent groups) should collapse into a toggle, with two
nesting levels — one for an individual tool/agent call, one for a run of
consecutive tool/agent calls — expanded while running, auto-collapsing once
that part of the turn finishes and the agent moves to the next part, with a
manual re-open. The collapsed outer toggle should show a short live-status
label (its own version of Claude's "Thinking...").

**Design:**
- **Level 2 (inner):** each individual `segment` of `type: 'tool'` (one tool
  call, or one nested step inside a delegated-agent group) gets its own
  collapse/expand affordance — this already exists today as `StepRow`'s
  chevron in `TraceView.tsx`; keep it, just formalize it as "level 2."
- **Level 1 (outer):** a *run* of consecutive tool-type segments (i.e. the
  span between two text segments, or from the start of the turn to the
  first text segment) is wrapped in one outer collapsible group. While any
  segment in that run is still actively streaming/pending, the group is
  forced open. The instant the run ends (a text segment begins, or the
  turn completes), the group auto-collapses to a single summary line
  (reusing/extending `TraceView`'s existing "N steps · M tool calls · K
  sources · Ts" summary row) with a manual expand control that persists
  after auto-collapse.
- **Live label:** while the outer group is open and running, show the most
  recent in-flight step's short description in place of (or alongside) the
  static summary — e.g. "Searching the web…", "Delegating to researcher…" —
  sourced from the same step-label text `TraceView` already renders per row,
  just surfaced at the group-header level too.
- **Where this lives:** `TraceView.tsx` groups consecutive tool segments
  today for rendering; this is primarily a state-machine addition (open/
  auto-collapsed/manually-reopened, per group, keyed by group start index)
  plus the header-label wiring, not a new data model — `Message.tsx`'s
  `segments` array (Phase N) already gives us natural run boundaries (a
  `'tool'`-type run bounded by `'text'`-type segments on either side).

*Files:* `frontend/src/components/TraceView.tsx` (primary), `Message.tsx`
(pass streaming/settled state per group if not already available).

**Open question to confirm before building:** should the outer group's
auto-collapse apply per-run (i.e., a turn with two separate tool-runs
separated by text gets two independently-collapsing groups), or should the
*whole turn's* trace collapse as one unit once the turn fully completes,
with level-1 groups only visible while expanded? The request describes
per-run behavior ("multi consecutive tool/agent calls specific") — building
to that reading unless corrected.

### P.2 — Fold rename/delete into the kebab menu

Currently `Sidebar.tsx` chat rows show a pencil (rename) and trash (delete)
icon on hover, separate from the "⋮" kebab that holds "Add to project"/
"Memory". Move rename and delete to be menu items inside the same kebab
dropdown (`KebabMenu.tsx` already supports plain non-submenu items), so
there's one hover-revealed affordance per row instead of three icons. Same
treatment for `ProjectRow.tsx`'s project-row kebab if it has the same
duplication (rename is already project-kebab-only per this session's live
testing; verify delete/rename placement on both chat and project rows for
consistency).

*Files:* `frontend/src/components/Sidebar.tsx`, `ProjectRow.tsx`,
`KebabMenu.tsx` (only if a new item shape is needed — current `MenuItem`
interface with plain `onClick` should already cover rename/delete).

### P.3 — Search relocation, rename, and cross-scope scope

- Rename the "Search chats" input's label/placeholder to "Search".
- Move it to sit directly below "Image Lab" in the sidebar (currently:
  New chat → Image Lab → Projects section → Chats section → Search chats
  input, buried inside the Chats section). New order: New chat → Image Lab
  → Search → Projects → Chats.
- Broaden the search itself: `Sidebar.tsx`'s `filteredConversations` today
  filters only `standaloneConversations` (`!c.project_id`) — confirmed via
  code read this session. Change to search across **all** conversations
  (standalone and project-scoped) and project names, so a match inside a
  project surfaces the project context too (e.g. group results or show a
  small project-name subtitle on matched project-chat rows).
- Make "New chat," "Image Lab," and "Search" render as the same-sized
  row/button (currently the two buttons and the search input likely have
  different padding/height — normalize via a shared class or component).

*Files:* `frontend/src/components/Sidebar.tsx` (main change — layout
reorder, filter broadening, shared sizing).

### P.4 — Project page opens directly into the chat area (Claude-style)

**Request:** clicking a project name should no longer show an intermediate
chat-list-only page (`ProjectPage.tsx` today); it should open straight into
the same chat/compose area used for regular chats — message composer, send/
receive, settings access — with a "project" section for the project's chat
history, matching the reference screenshot's layout: breadcrumb
("Projects / NAME"), header with pin/kebab, composer immediately below,
then a "Recents"-style list of the project's chats underneath, all in one
page. Keep only the features PAWN already has (no pin, since that's not a
current feature unless we're told to add it) — match the *format*, not the
full feature set.

**Design (needs your confirmation on the exact composer behavior before
building):**
- Route `/project/:projectId` (currently `ProjectPage.tsx`, a list-only
  view) to render a composer + "Recents" list directly, instead of
  requiring a click into `/project/:projectId/chat/:id` first.
- Sending a message from this project-level composer with no chat selected
  yet should lazy-create a new chat scoped to the project (mirroring how a
  draft standalone chat lazy-creates today) and transition into that chat's
  own view/URL — i.e., this page *is* the project's "new chat" composer,
  not a separate button leading to one.
- The project's existing chats render below the composer as a "Recents"-
  style list (reusing `ProjectPage.tsx`'s current chat-row rendering,
  relabeled/restyled), each still clickable to open that specific chat.
- `/project/:projectId/chat/:id` (an already-open chat inside a project)
  keeps working as today — this change only affects the *landing* page you
  hit by clicking the project name itself, before any chat is selected.

*Files:* `frontend/src/pages/ProjectPage.tsx` (major rewrite — likely
absorbs much of `ChatPage.tsx`'s composer/layout, or `ChatPage.tsx` grows a
"no active chat, project context" mode it renders through), routing in
whichever router config file owns `/project/:projectId`.

**Gate for all of P:** `tsc -b` + `vite build` clean; manually drive each
of P.1–P.4 in the browser (this session's Chrome access) before calling any
of them done, per this project's UI-verification norms.

---

## 5. Phase O.2 → O.3 → O.4 — deep research quality, verifier, decomposition

No changes to the source plan — build in order per `plan_reply_quality.md`
§§4.2–4.4 and §5, re-running the green-hydrogen benchmark after each to
attribute the gain. Not re-detailed here; see that file.

---

## 6. Image Lab warm-session issues (independent, user-paced)

No changes to the source plan (`plan_imagelab_session_issues.md`). Next
step per that doc is gathering concrete repro details (which model, which
phase Stop was clicked in, UI vs. kaggle.com state, whether the session
predates the supervisor-thread deploy) — a human-in-the-loop debugging
session on the user's real Kaggle account, not something to blindly code
against further. Can run in parallel with 1–4 above whenever convenient.

---

## 7. Tracker registration

Register in `workspace/status/build_tracker.md` as:
- Phase N (already referenced as "Phase N" in its own source plan) — status flips from "in progress" to a proper tracked entry once §2 lands.
- Phase O — as already named in its source plan.
- **Phase P (new)** — the four UI items in §4.
- Image Lab issues stay as their own untracked, paused thread (per that plan's own header) rather than a numbered phase, since it's explicitly not ready for a build cycle.
