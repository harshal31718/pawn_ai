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
