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
