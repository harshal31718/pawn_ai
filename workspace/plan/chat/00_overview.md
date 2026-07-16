# Chat — Feature Additions & Enhancements (Overview)

**Status:** PLANNED. **Branch:** `dev`. **Folder:** `workspace/plan/chat/`
**Date:** 2026-07-15

## 1. Why this plan exists

Following user feedback on 2026-07-15, we are establishing a dedicated planning folder for the **chat/project/agentic** section of PAWN. This plan addresses key issues in model orchestration routing, deployed agent reliability, and UI warning banners.

## 2. File index

| File | What |
|---|---|
| `00_overview.md` | This file |
| `phase_F1_image_generation.md` | Chat feature: `generate_image` agent tool (recovered from the deleted 2026-07-15 findings plan) |
| `phase_F2_model_switcher.md` | Search-tab ModelSwitcher — **needs re-verification**, premise didn't reproduce against current code |
| `phase_F6_groq_default.md` | Model Routing: Prioritize Groq API as the default orchestrator when a Groq key is added |
| `phase_F7_agent_half_generation_fix.md` | Agent Reliability: Fix the half-generation issue where agents composition completes but leaves an empty reply |
| `phase_F8_sync_warning_relocation.md` | Sidebar UI: Relocate the "changes not yet synced" warning banner to the bottom of the sidebar |
| `phase_F9_sidebar_scroll_and_project_ui.md` | Sidebar scroll bug (chats unreachable) + clumsy active project/chat row styling — **fixes applied in code 2026-07-15**, see file for what shipped |
| `phase_F10_projects_gallery_page.md` | New Projects gallery page (cards w/ description) + sidebar projects-list cap — **plan only, needs 3 open questions answered before build** |
| `open_items.md` | Other open/parked items (Drive-mandatory wording [DONE], repo mirror [parked], Kaggle LLMs [parked]) |

## 3. Ground rules

- **Branch:** `dev`, additive changes only. Never refactor live paths.
- **Process:** Use the `build-step` skill per numbered step; register steps in `workspace/status/build_tracker.md` before starting.
- **Verification:** Standard gates: full backend suite green, frontend `tsc` and build clean, live verification in the browser.

## 4. Suggested Order

1. **F-9: Sidebar scroll bug** ([phase_F9_sidebar_scroll_and_project_ui.md](file:///c:/Users/harsh/Desktop/PAWN/workspace/plan/chat/phase_F9_sidebar_scroll_and_project_ui.md)) — live navigation blocker; the scroll-region and projects-list-cap fixes already landed in code this session (§3.1/sidebar cap), the nested-row visual polish (§3.2) also landed; only live-browser re-verification remains.
2. **F-7: Agent Half-Generation Fix** ([phase_F7_agent_half_generation_fix.md](file:///c:/Users/harsh/Desktop/PAWN/workspace/plan/chat/phase_F7_agent_half_generation_fix.md)) — critical reliability fix, root cause confirmed against current `graph.py`.
3. **F-8: Relocate Sync Warning** ([phase_F8_sync_warning_relocation.md](file:///c:/Users/harsh/Desktop/PAWN/workspace/plan/chat/phase_F8_sync_warning_relocation.md)) — quick UI fix, confirmed against current `Sidebar.tsx` line numbers.
4. **F-6: Groq as Default Orchestrator** ([phase_F6_groq_default.md](file:///c:/Users/harsh/Desktop/PAWN/workspace/plan/chat/phase_F6_groq_default.md)) — orchestrator optimization, scope narrowed during refinement (see file §2's scope note).
5. **F-2: Model switcher (needs re-verification first)**, **F-1: Image gen from chat** — filler-sized items once F-2's premise is confirmed live.
6. **F-10: Projects gallery page** — needs the 3 open questions answered before it's buildable; biggest single item in this folder.
