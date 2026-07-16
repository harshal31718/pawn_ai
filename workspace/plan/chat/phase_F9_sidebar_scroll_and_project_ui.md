# Phase F-9 — Sidebar Scroll Bug + Clumsy Project-Chat Row Styling

**Status:** PLANNED. **Branch:** `dev`. **Folder:** `workspace/plan/chat/`
**Date:** 2026-07-15 — from the user's live screenshots of the deployed sidebar.

## 1. Why this plan exists

Two related sidebar bugs, both observed live:

1. **Projects/Chats list is not scrollable.** Screenshot shows 2 projects
   (`fasdfsad`, `research`) and a "CHATS" section with only "New Chat" visible —
   the user reports 3 chats exist but only 1 is visible and the list cannot be
   scrolled to reach the rest.
2. **Expanding a project's chat looks clumsy.** Screenshot shows the active
   project row (`fasdfsad`, expanded) and its nested "New Chat" row rendering as
   a bright, sharp-edged light card that visually clashes with — and partially
   overlaps — the dark sync-warning banner directly above it, instead of reading
   as one coherent list.

## 2. Root cause (verified against code, 2026-07-15)

### 2.1 Scroll bug

`Sidebar.tsx`'s expanded layout (`:207` onward) stacks, top to bottom: header,
New chat, Image Lab, Search, the sync-warning banner (all `shrink-0`, fixed),
then — only when *not* searching — `ProjectSection` (`:304`, **no scroll
wrapper of its own**) followed immediately by the flat chat list, which alone
is wrapped in `flex-1 overflow-y-auto` (`:333`). `ProjectSection` sits as a
plain sibling *outside* that scrollable div. So:

- `ProjectSection`'s own content (project rows + their expanded chat rows) has
  no bounded height or scroll of its own — it just grows.
- The chat-list div's `overflow-y-auto` only ever gets whatever vertical space
  is left after everything above it (including the now-unbounded
  `ProjectSection`) is laid out — with 2+ projects (one expanded), that
  remaining space can shrink to near-zero, hiding chats with no way to reach
  them since only the chat-list div scrolls, not the page/section that
  actually needs it.

This is the classic nested-flexbox scroll bug: a single shared `flex-1
min-h-0 overflow-y-auto` region is needed around *both* `ProjectSection` and
the chat list, not just the chat list alone.

### 2.2 Clumsy project-chat styling

`ProjectRow.tsx`'s active-state classes (`:70-73` for the project row itself,
`:143-145` for a nested chat row) both use `bg-theme-brand text-theme-brand-text
shadow-sm` when active/selected. Two things make this look "clumsy" once a
project is expanded right under the sync-warning banner:

- No spacing/visual break is enforced between the sync-warning banner
  (`Sidebar.tsx:280-287`) and `ProjectSection`'s first row — when the project
  right below is also `active` (bright `bg-theme-brand` pill), the two
  differently-colored bordered boxes sit flush against each other with no
  breathing room, reading as one broken shape rather than two distinct
  elements.
- The nested chat row (`ProjectRow.tsx:139-146`) reuses the exact same
  `bg-theme-brand`/`shadow-sm` active treatment as the top-level project row,
  with no visual demotion (smaller shadow, no elevation, etc.) for being one
  level deeper — an active top-level row and an active nested row look
  identically "loud," so the nested one reads as a floating card rather than
  a subordinate list item.

## 3. Proposed changes

### 3.1 Fix the scroll bug (priority — currently makes chats unreachable)

`frontend/src/components/Sidebar.tsx`:
- Wrap `ProjectSection` and the existing chat-list `<div className="flex-1
  overflow-y-auto ...">` (`:333`) together in one shared scroll container:
  `<div className="flex-1 min-h-0 overflow-y-auto ...">` holding both
  `ProjectSection` and the chat list's own contents (drop the inner div's now-
  redundant `flex-1 overflow-y-auto`, keep its `px-2 py-2 space-y-1` styling).
- Verify the ancestor chain down from `:207`'s `flex flex-col h-full` actually
  constrains height — `overflow-hidden` on `:207` plus `shrink-0` on every
  fixed block above should already give the wrapping `flex-1 min-h-0` div a
  correctly bounded height; confirm this live rather than assuming, since
  flexbox min-height collapse bugs are exactly the kind of thing that "looks
  right in the JSX" but isn't.
- Manual verification: seed 3+ chats and 2+ projects (one expanded with 2+
  chats) in a short/laptop-height viewport; confirm the whole projects+chats
  region scrolls as one unit and every chat is reachable, while header/New
  chat/Image Lab/Search/sync-banner and the bottom profile card stay pinned.

### 3.2 Fix the clumsy project-chat visual (secondary — cosmetic)

`frontend/src/components/ProjectRow.tsx`:
- Give the nested chat row (`:142-146`) a visually distinct, quieter active
  state than the top-level project row — e.g. drop `shadow-sm` for nested
  rows, or use a lighter/tinted background (`bg-theme-brand/15` with
  `text-theme-text` instead of the full-strength brand fill + brand-text
  color) so depth reads visually, not just via indentation.
- `Sidebar.tsx`: add a small margin (`mb-2` or similar) after the sync-warning
  banner block (`:280-287`) so it never sits flush against the Projects
  section's first row regardless of that row's active state.
- Manual verification: expand an active project with an active nested chat,
  confirm the two levels read as a coherent nested list, not two overlapping
  cards; re-check with the sync-warning banner both present and absent.

## 4. Suggested priority

This is a **live-blocking navigation bug** (§3.1) plus a cosmetic follow-up
(§3.2) — rank above F-6 (orchestrator optimization) and alongside/just after
F-7 (agent reliability) given how directly it affects basic usability. Both
fixes are additive/CSS-only, no backend touch, low risk. `npm run build` +
live browser check are the only gates needed (no backend tests apply).

## 5. DONE (2026-07-16) — live verification + sticky section headers

Live-verified against the real `docker compose watch` stack via Chrome:
expanding both projects (`asdgasd`, `suiiiii`) under a constrained-height
sidebar pushed the flat chat list out of view; scrolling the shared
`flex-1 min-h-0 overflow-y-auto` region (Sidebar.tsx) reached the hidden
chat while header/New chat/Image Lab/Search/profile card all stayed pinned,
confirming §3.1. The nested chat row's quieter `bg-theme-brand/15` active
state (§3.2) was also confirmed visually against the top-level project row's
full-strength `bg-theme-brand`.

**Follow-up requested live by the user this same session:** lock ("stick")
the "Projects" and "Chats" section-label rows to the top of the shared
scroll region while their own lists scroll underneath — the classic
sticky-section-header pattern. Implemented additively:
- `ProjectSection.tsx`: the "Projects" header row (label + new-project
  button) gained `sticky top-0 z-10 bg-theme-surface`.
- `Sidebar.tsx`: the "Chats" label row gained the same
  `sticky top-0 z-10 bg-theme-surface`.
- Both are direct children of the shared scroll container from §3.1, so the
  hand-off works automatically: each header stays stuck to the top only
  while its own section is still scrolling past, per normal CSS `sticky`
  containing-block behavior — no extra JS needed.

Live-verified: scrolling with both projects expanded let `asdgasd` scroll
out of view while the "Projects" label stayed fixed at the top of the
sidebar list; `tsc --noEmit` and `npm run build` both clean.
