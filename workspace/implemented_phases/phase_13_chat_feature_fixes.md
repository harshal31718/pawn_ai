# Phase 13 — Chat Feature Fixes & Polish (F-1/F-2/F-3/F-6/F-7/F-8/F-9/F-10)

*Branch: `dev`. Status: DONE 2026-07-16 (F-3 done 2026-07-15, everything else
2026-07-16). Originally planned across `workspace/plan/chat/` — this file is
the closed-out record; the per-item plan files themselves were removed from
`plan/chat/` once done (see `workspace/plan/README.md`/`build_tracker.md` for
the folder's current empty-and-ready-for-future-plans state).*

## 1. Why this phase existed

A batch of chat/project UI bugs, one agent reliability bug, and a handful of
small feature requests accumulated across two planning sessions
(2026-07-15/16) in `workspace/plan/chat/`. This phase closes all of them out
in one build pass, auto-proceeding item by item with live verification via
Chrome against the running `docker compose watch` stack.

## 2. What shipped

### F-9 — Sidebar scroll bug + project/chat row styling
Root cause: `ProjectSection` sat outside the sidebar's own scroll region, so
its unbounded height could push the flat chat list out of reach with no way
to scroll to it. Fix: one shared `flex-1 min-h-0 overflow-y-auto` region
wraps both `ProjectSection` and the chat list in `Sidebar.tsx`. Also gave the
nested chat row inside an expanded project a quieter `bg-theme-brand/15`
active state instead of reusing the top-level project row's full-strength
fill. **User follow-up, same pass:** sticky "Projects"/"Chats" section
labels (`position: sticky; z-index: 10`) so they stay pinned while their own
lists scroll underneath.

### F-7 — Agent half-generation / empty-reply fix
Root cause: on a heavy turn's clean stop, `execute_node` (`agent/graph.py`)
appended the orchestrator's own discarded draft as a trailing `assistant`-
role message right before the mandatory closing-synthesis call. Several
providers (Gemini's OAI-compat layer, confirmed) reject or silently empty
out a completions request whose tail message is already assistant-authored
— this cascaded into an empty `verify_draft` and a fully silent reply after
"Composing final answer". Fixed: that draft is now a non-terminal `system`
context note instead; the closing-synthesis call is wrapped in the same
try/except-and-fall-back-to-loop-draft pattern the tool loop already used;
a shared `_EMPTY_REPLY_FALLBACK` apology closes a residual double-failure
gap (loop never ran + synthesis also failed) in both `execute_node` and
`verify_node.accept()`. Live-verified end to end: a real heavy/research
query with a genuine mid-flight provider failover synthesized a full answer.

### F-8 — Sync warning banner relocation
Moved the "some changes are not yet synced" banner in `Sidebar.tsx` from
directly under the Search box (pushing the Projects/Chats lists down) to
directly above the User Profile Card at the bottom. Straight cut-paste.

### F-6 — Groq priority in the model resolver
When the user holds a Groq BYOK key, `Resolver.pick_model_by_capability`
now reorders a capability level's candidate models so Groq-endpoint-having
ones try first (large rate limits, fast generation) — affects the
orchestrator, execute-loop, final-synthesis, and subagent picks, since all
of them route through this one function. The plan's premise that
`ModelEntry` itself carries a `provider` field was wrong (only
`EndpointEntry` does — one model can span several providers); implemented
instead via a new `Resolver._has_groq_endpoint(model_id)` check feeding a
stable sort ahead of the existing usable-endpoint fallback loop (untouched,
so a rate-limited/keyless Groq endpoint still correctly falls through).

### F-1 — Chat-side `generate_image` agent tool
New `agent/tools/generate_image.py`: checks for a live warm Kaggle session
first (`submit_session_job`), else a cold one-shot job
(`create_cold_job` + background worker), returning a `job_id` immediately —
never blocks the tool loop on a multi-minute render. Gated on a new
`key_store.has_kaggle_creds(user_id)`. New `components/ImageJobChip.tsx`
polls the job and renders the finished image inline inside `TraceView.tsx`.
**Cross-module race found and fixed mid-build:** the tool's first draft
duplicated `routes/generate.py`'s own per-(user,model) cold-job lock/
background-task bookkeeping as a separate copy, so a cold run triggered
from chat and one from Image Lab for the same model could still race the
same single-writer Kaggle kernel slug. Centralized into
`core/image_session.py`'s `spawn_cold_job_bg`, shared by both entry points.

### Bonus fix found the same session — chat auto-titling
Every chat was silently stuck on the literal "New Chat". Root cause:
`routes/chat.py`'s `generate_title` called `pick_model_by_capability("fast")`
**without** `user_id`, so it could pick a model the user holds no key for;
the follow-up `chat_stream` call (which does get the real `user_id`) then
failed on the missing key, and the exception was silently swallowed. Fixed:
`user_id` now passed through; new `core/title.py`'s
`derive_fallback_title(first_prompt)` (no LLM call — whitespace-collapsed,
word-boundary-truncated) replaces the bare `"New Chat"` fallback so a title
is always something real even if every model call fails.

### F-2 — Search-tab ModelSwitcher — closed as **not a bug**
User's concrete concern (Groq configured, some models still missing from
the picker) traced live: the only models missing are the ones whose sole
provider is OpenRouter, which had no key configured. Both the frontend's
provider-based filter (`AppContext.tsx`) and the backend's
`pick_model_by_capability` are correctly and consistently gated on the same
BYOK key check — the backend is not more restrictive than the picker. No
code changes; closed after live investigation, not built.

### F-10 — Projects gallery page + project descriptions
Projects gained a `description` field end to end (`projects_drive.py`'s
`create_project`/`update_project` — generalized from the old rename-only
`rename_project` — `routes/projects.py`, frontend `types.ts`/`client.ts`,
plus a full `updateProjectDescription` sync-queue op mirroring
`renameProject`'s exact optimistic-update/offline-retry shape). New
`EditProjectDetailsModal.tsx` (Name + Description; Archive intentionally
skipped per the user, after they compared against a reference UI that had
one) wired into `ProjectPage.tsx`'s kebab menu. New `ProjectsGalleryPage.tsx`
at `/projects` — sort (last-updated/name), search, responsive card grid —
reached by clicking the sidebar's "Projects" label (its collapse toggle was
split into its own small chevron so that behavior wasn't lost).

**Live-reported polish fixed in the same pass:**
- `ModelSwitcher.tsx`'s dropdown always opened upward assuming the trigger
  sits near the viewport bottom; now computes direction + a capped height
  from the trigger's actual available space.
- `KebabMenu.tsx`'s dropdown rendered behind F-9's sticky section labels — a
  `position: sticky` + `z-index` element always paints above a
  non-positioned ancestor's whole subtree per CSS stacking rules, so a
  descendant's own z-index can never out-rank it locally. Fixed by
  rendering the open dropdown through a React portal into `document.body`.
- `EditProjectDetailsModal`'s overlay centered over the whole viewport
  (sidebar included) instead of the content area next to it — switched from
  `fixed inset-0` to `absolute inset-0` scoped to `ProjectPage`'s own
  `relative` wrapper.
- `ChatPage.tsx`'s `{project}/{chat}` header title was one concatenated
  string with no spacing/click target — split into structured JSX (a
  clickable project-name link + spaced `/` + chat title).
- `ProjectPage.tsx`'s "← All projects" was a plain in-flow breadcrumb line,
  inconsistent with the floating top-left pill tab `ChatPage`/`SettingsPage`
  both already use — replaced with the same pattern.

### F-3 — Drive-mandatory wording (done 2026-07-15, closed out here)
Docs-only: clarified that Drive is the durable source of truth (chats,
`rag_chunks.jsonl`, upload manifest) and Postgres is the derived, rebuildable
index — applied to `decisions/project_overview.md` and
`implemented_phases/phase_10_drive_mandatory.md`.

## 3. Deliberately not built

- **F-4 — Private/public repo mirror.** Not a code change — an ops runbook
  for if/when PAWN goes public. Moved to `deployment.md` §8 (Known
  deferrals) as a required step before ever flipping the OAuth consent
  screen to Production/public, alongside the existing PostgREST
  scoped-JWT deferral.
- **F-5 — Kaggle-hosted LLM API.** Scrapped outright (assessed as a bad
  plan) — PAWN's existing BYOK provider layer (Groq/Cerebras/Gemini) already
  gives fast, free-tier models with failover at far lower latency than a
  Kaggle round-trip could ever offer. Not carried forward anywhere.

## 4. Verification

Full backend suite green (467 tests via `docker compose exec backend
pytest -n auto`); `tsc --noEmit` + `npm run build` clean throughout. Every
item live-verified via Chrome against the real `docker compose watch`
stack — F-7's fix specifically exercised with a genuine heavy/research
query including a real mid-flight provider failover; F-10's gallery page,
modal, and sidebar navigation confirmed directly by the user
("works, i tested it").
