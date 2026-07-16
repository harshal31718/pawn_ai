# Phase F-10 — Projects Gallery Page + Sidebar Projects List Cap

**Status:** PLANNED (plan-only — no code written for this item). **Branch:** `dev`.
**Folder:** `workspace/plan/chat/`
**Date:** 2026-07-15 — from the user's live screenshot + follow-up request.

## 1. Why this plan exists

The sidebar's Projects list has no upper bound — with 5+ projects it just grows,
eating space the Chats list needs (see F-9 for the scroll-region fix, already applied
in code this session). The user asked for two related things:

1. Sidebar: don't show every project inline — cap it with its own fixed-size scroll
   region (**already applied in code this session** — `ProjectSection.tsx`'s project
   list div gained `max-h-56 overflow-y-auto`; leave as-is, no further action needed
   here unless the user wants a different cap height after seeing it live).
2. **New:** a dedicated Projects page — clicking into "Projects" (not an individual
   project row) opens a gallery view showing every project as a square/rectangle card
   with a description, separate from the sidebar's compact list. Clicking an
   individual project row in the sidebar must keep its current behavior unchanged
   (opens `ProjectPage` directly, per the user's explicit instruction) — the gallery
   is an additional entry point, not a replacement.

## 2. Current state (verified against code, 2026-07-15)

- `Project`/`CachedProject` (`frontend/src/types.ts`) has no `description` field —
  today a project is just `{id, name, chat_count, ...sync bookkeeping}`.
- Backend `ProjectCreate`/`ProjectUpdate` (`backend/app/routes/projects.py:25-31`) only
  carry `name` — no description anywhere in the create/rename/list path or in
  `projects_drive.py`'s Drive-persisted `project.json`.
- Routing (`frontend/src/pages/`) has `ChatPage`, `ProjectPage`, `ImageLabPageWrapper`,
  `SettingsPageWrapper`, `LandingPage`, `PrivacyPolicyPage` — no gallery-style project
  list page exists yet.
- Sidebar's "PROJECTS" label (`ProjectSection.tsx:64-70`) currently only toggles
  collapse/expand of the inline list — it has no navigation behavior today, so adding
  one doesn't break an existing user-facing action.

## 3. Proposed changes (for a future build-step session)

### 3.1 Backend — add `description` to the project model

- `backend/app/routes/projects.py`: `ProjectCreate` and `ProjectUpdate` gain
  `description: str | None = None`.
- `backend/app/storage/projects_drive.py`: `create_project`/`rename_project` (or a new
  `update_project`) persist `description` into the Drive-stored `project.json`;
  `list_projects`/`get_project_meta` return it.
- Decide: is `description` editable via the existing `PATCH /projects/{id}` (rename)
  endpoint extended to accept both fields, or does it need its own endpoint? Extending
  the existing one is simpler and matches the "additive, no refactor" house rule.

### 3.2 Frontend — types + client

- `types.ts`: `Project`/`CachedProject` gain `description?: string`.
- `client.ts`: `createProject`/`renameProject` gain an optional `description` param;
  `useConversationStore.ts`'s matching mutators/sync-queue payloads follow.

### 3.3 Frontend — new gallery page

- New route (e.g. `/projects`) + new page component (e.g. `ProjectsGalleryPage.tsx`)
  rendering every project as a card (name, description, chat count, folder icon) in a
  responsive grid — square/rectangle cards per the user's request.
- Clicking a card navigates to the existing `/project/:projectId` (`ProjectPage`) —
  identical destination to today's sidebar row click, just a second entry point.
- Sidebar: add a lightweight "See all" affordance (e.g. small link/icon near the
  "PROJECTS" header or after "New project") that navigates to `/projects`. **Do not**
  repurpose the "PROJECTS" label's existing collapse-toggle click or any
  `ProjectRow` click — both must keep their current behavior exactly, per the user's
  explicit instruction.
- Where does "description" get entered/edited? Not specified by the user yet — options:
  (a) add an optional description field to `NewProjectRow`'s create flow, (b) make it
  editable only from the new gallery page (e.g. an inline edit or a small pencil icon
  on each card). Needs a quick confirm before building — flagged as an open question.

## 4. Open questions before this becomes buildable

1. Where can a user actually set/edit a project's description — at creation time in
   the sidebar's "New project" flow, from the gallery page, or both?
2. Exact trigger for opening the gallery page from the sidebar (a "See all" link, an
   icon next to "PROJECTS", or something else)?
3. Any specific card layout preference (grid columns, fixed card size, what shows
   besides name/description/chat-count — e.g. last-updated date)?

## 5. Suggested priority

Cosmetic/organizational, not a live bug — rank below F-9 (scroll fix, done) and the
reliability-critical items (F-7), similar tier to F-6/F-8. Backend touches Drive
storage + a Pydantic model (small, additive) but the frontend gallery page is genuinely
new surface area, sized for its own build-step run rather than a "quick filler" item.

## 6. DONE (2026-07-16) — open questions answered live, then built

User answered the 3 open questions live (with reference screenshots from Claude's own
Projects UI):
1. Description is edited via a kebab "Edit details" modal (Name + Description fields,
   Save/Cancel) on `ProjectPage` — not at creation time. "Archive" (visible in the
   reference UI) explicitly skipped per the user's instruction.
2. Clicking the sidebar's "Projects" label itself now navigates to the new gallery
   page; the collapse toggle was split out into its own small chevron button right
   before the label so neither behavior was lost.
3. Card layout: name (uppercase) + description (2-line clamp, no "Show more" needed at
   card size) + last-updated date, responsive 1/2-column grid, plus a "Sort by"
   (Last updated / Name) control and a search box — matching the reference screenshots.

**Backend:** `projects_drive.py`'s `create_project` gained `description: str = ""`;
`rename_project` generalized into `update_project(drive, project_id, name=None,
description=None)` (either field independently updatable, matching the plan's "extend
the existing PATCH" call). `routes/projects.py`'s `ProjectCreate`/`ProjectUpdate` gained
`description`. 4 new/updated tests in `test_projects_drive.py`, full suite green (467).

**Frontend:** `Project`/`CachedProject` gained `description?: string`; new
`updateProjectDescription` client helper + a full sync-queue op (`SyncOp`,
`useConversationStore`, `syncQueue.ts`) mirroring `renameProject`'s exact
optimistic-update/offline-retry pattern — not bolted on ad hoc. New
`EditProjectDetailsModal.tsx` (Name + Description, no Archive) wired into
`ProjectPage.tsx`'s kebab menu (replacing "Rename"); description renders under the
title with a 2-line clamp + "Show more/less" toggle past 140 chars. New
`ProjectsGalleryPage.tsx` (route `/projects`) — header, sort dropdown, search, card
grid; "New project" creates + navigates straight to the new project (same
create-then-navigate pattern `createConversation` already uses). `ProjectSection.tsx`'s
sticky "Projects" label now navigates there, with collapse split into its own chevron
button. `tsc --noEmit` + `npm run build` clean.

**Also fixed in the same pass (user-reported live, found while testing this):**
`ModelSwitcher.tsx`'s dropdown always opened upward assuming the trigger sits near the
viewport bottom (true in the main chat composer, not true on `ProjectPage` or a short
window) — overflowed off the top of the screen. Now computes direction (up/down) and a
capped max-height from the trigger's actual `getBoundingClientRect()` on open, so it's
never clipped either direction.

Live-verified by the user directly ("works, i tested it") — Edit details modal, the
Projects gallery navigation, and card rendering all confirmed working against the real
`docker compose watch` stack.
