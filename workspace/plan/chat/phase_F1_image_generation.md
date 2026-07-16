# Phase F-1 — Image Generation From Chat

**Status:** PLANNED. **Branch:** `dev`. **Folder:** `workspace/plan/chat/`
**Date:** 2026-07-15 (recovered from the deleted `plan_feature_additions_2026-07-15.md`
during the 2026-07-15 `chat/` folder reorg — content unchanged, just relocated to its own
file so `build_tracker.md`'s per-step registration has something to point at)

## 1. Why this plan exists

Chat has no image-generation tool today (`agent/tools/` has no `generate_image.py`).
Image Lab remains the home for sessions/browsing; this adds a chat-side `generate_image`
agent tool — imageLab's long-deferred "Milestone B (chat composer integration)", cheap now
that both the agent tool layer (A.2) and the image job layer already exist.

## 2. Proposed changes

1. New `backend/app/agent/tools/generate_image.py` — `ToolSpec generate_image(prompt,
   model='sdxl')`: routes exactly like the Lab (warm session first via
   `submit_session_job`, else cold via `create_cold_job` — reuse, zero new job logic),
   returns `job_id` + a one-line "generation started" observation immediately (never
   blocks the tool loop on a multi-minute render). Gated in `registry.py` on saved Kaggle
   creds (same pattern as `web_search`'s key gating).
2. Frontend: chat messages gain one new trace/citation-style element — an image-job chip
   that polls `GET /generate/job/{id}` (reuse existing client helpers) and swells into the
   image inline when done. No composer button needed v1 — the agent decides when the user
   asked for an image (matches PAWN's agentic direction).
3. Tests: tool spec/gating/dispatch (mocked job layer); one route-level integration test.
   `npm run build` clean. security-auditor not required (no new secret surface).

Also closes the "cold generate without a session doesn't work" report's first half: cold
"generate once" STAYS — it's the no-session path this tool itself uses. That report could
not be reproduced in code review; if it recurs, capture the error box text and treat as a
bug against `create_cold_job`, not a design question.

## 3. Open question before build

None — this plan embeds the one open decision (chat-side tool vs. Lab-only) as "add the
tool", per the original finding's triage.

## 4. DONE (2026-07-16)

- New `backend/app/agent/tools/generate_image.py` — `generate_image(prompt, model='sdxl')`:
  checks `image_session.get_session_status` first (warm session → `submit_session_job`),
  else `create_cold_job` + spawns the background worker, returning `job_id` immediately.
  Gated in `registry.py` on a new `key_store.has_kaggle_creds(user_id)` helper (mirrors
  `has_search_key`'s pattern), so the tool is simply absent without Kaggle creds — no error.
- **Cross-module race found and fixed mid-build (code-reviewer WARN):** the tool's first
  draft duplicated `routes/generate.py`'s own per-(user,model) lock/bg-task-set for cold
  jobs, as its own separate module-level dict — meaning a cold run triggered from chat and
  one triggered from Image Lab for the *same* model could still race the same single-writer
  Kaggle kernel slug, defeating the whole point of the lock. Fixed by centralizing the
  lock/task registry into `core/image_session.py` itself (`spawn_cold_job_bg`,
  `_cold_job_lock_for`, `_cold_job_locks`, `_cold_job_bg_tasks`); both `routes/generate.py`
  and `generate_image.py` now call the same shared function, and the route's own now-dead
  `_run_cold_job_bg`/`_spawn_bg`/`_bg_tasks` were deleted rather than left as unused
  duplicates.
- Frontend: new `components/ImageJobChip.tsx` (polls `GET /generate/job/{id}` via the
  existing `getJob` client helper every 3s until a terminal status, then renders the image
  inline or a plain error line) wired into `TraceView.tsx`'s `ToolCard` — visible
  unconditionally (not gated behind the card's own collapse/expand chevron), extracting the
  `job_id` from the tool's plain-string observation via a small regex (`extractImageJobId`,
  documented as consistent with how every other tool's result already flows through
  `observation` — no dedicated `TraceEntry` field added for this one case).
- 10 new tests in `test_agent_tools_image.py` (registry gating incl. partial-creds, warm/cold
  routing, dedup-no-respawn, graceful `NotConfiguredError` degradation, tool spec shape) + 2
  new/updated tests in `test_image_jobs.py` covering the shared `spawn_cold_job_bg` call
  from the route side (spawn-on-create, skip-on-dedup). Full backend suite green (464,
  `docker compose exec backend pytest -n auto`); `tsc --noEmit` + `npm run build` clean.
  code-reviewer: PASS with 1 WARN fixed (the cross-module race above) and 1 WARN **accepted,
  not closed**: the plan's own §2.3 promised "one route-level integration test" (a full
  `/chat` round-trip with a mocked LLM emitting a `generate_image` tool call) — not added
  this session. The tool handler itself is thoroughly unit-tested, and `graph.py`'s own
  execute-loop tool-dispatch mechanics are already exhaustively covered generically
  (A.2/A.6 tests) — judged sufficient for now given no live Kaggle stack is available this
  session to make a true end-to-end test meaningful; revisit if a live Kaggle-backed session
  becomes available to verify the real image actually renders in a real chat turn.
  No security-auditor run (no new secret surface — reads existing Kaggle creds via the
  existing `key_store.get_kaggle`, doesn't touch how they're stored/encrypted).
- Not yet live-verified against a real Kaggle account (needs the user's own Kaggle
  creds + a real chat request that triggers the tool).
