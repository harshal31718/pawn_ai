# Chat — Feature Additions & Enhancements (Overview)

**Status:** No active plans. **Branch:** `dev`. **Folder:** `workspace/plan/chat/`
**Last cleared:** 2026-07-16

## What this folder is

Planning home for the **chat/project/agentic** section of PAWN. Kept empty
and ready — drop new phase files here (`phase_FN_description.md` naming, per
the prior batch) whenever new chat-side work is planned.

## Where the last batch went

F-1/F-2/F-3/F-6/F-7/F-8/F-9/F-10 (image-gen tool, model-switcher
investigation, Drive-mandatory wording, Groq resolver priority, agent
half-generation fix, sync-warning relocation, sidebar scroll fix, Projects
gallery page) all shipped 2026-07-16 — closed-out record at
`workspace/implemented_phases/phase_13_chat_feature_fixes.md`. F-11 (attach
image + forced-SDXL session) shipped 2026-07-16 — closed-out record at
`workspace/implemented_phases/phase_F11_chat_io_formats.md`.

F-4 (repo mirror runbook) moved into `deployment.md` §8 as a pre-public-launch
step. F-5 (Kaggle-hosted LLM API) was scrapped outright, not carried forward.

## Ground rules (unchanged for future work here)

- **Branch:** `dev`, additive changes only. Never refactor live paths.
- **Process:** Use the `build-step` skill per numbered step; register steps in
  `workspace/status/build_tracker.md` before starting.
- **Verification:** Standard gates: full backend suite green, frontend `tsc`
  and build clean, live verification in the browser.
