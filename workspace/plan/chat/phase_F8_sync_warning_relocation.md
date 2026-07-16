# Phase F-8 — Sidebar Sync Warning Relocation

**Status:** PLANNED. **Branch:** `dev`. **Folder:** `workspace/plan/chat/`
**Date:** 2026-07-15

## 1. Why this plan exists

The warning banner `"Some changes are not yet synced..."` (rendered when `syncError` is present) is currently placed at the top of the sidebar, directly below the Search input box. This pushes down the projects section and conversations list, causing visual clutter and disrupting navigation controls. We want to relocate this warning banner to the bottom of the sidebar, directly above the User Profile Card, where it remains prominent but less intrusive.

**Verified against current code (2026-07-15 refinement pass):** exact line numbers
confirmed — the banner block is `Sidebar.tsx:280-287`, the `{/* User Profile Card */}`
comment is at `Sidebar.tsx:452` (now shifted slightly by F-9's scroll-region wrapper
edit — re-grep both spots at build time rather than trusting these line numbers
verbatim, since F-9 already touched this file this session). Both blocks are plain
`shrink-0` divs, so relocating is a straight cut-paste with no layout-flow surprises.

## 2. Proposed Changes

### 2.1 Frontend

#### [MODIFY] [Sidebar.tsx](file:///c:/Users/harsh/Desktop/PAWN/frontend/src/components/Sidebar.tsx)
- Remove the offline/unsynced changes banner block from its current layout position (under the Search container wrapper).
- Move this block to the bottom of the sidebar, placing it directly above the User Profile Card container wrapper (`{/* User Profile Card */}`).
- Adjust styles, padding, or margins if necessary to ensure it matches the bottom layout flow.

## 3. Verification Plan

### Manual Verification
- Simulate an unsynced changes error or disconnect the network to trigger a `syncError` status.
- Open the sidebar in the UI.
- Verify that the warning box `"Some changes are not yet synced..."` displays cleanly at the very bottom of the sidebar list, right above the user profile section.
- Ensure the project and conversation list items are no longer pushed down by the warning box at the top.
- Confirm `npm run build` is clean and has no compiler errors.
