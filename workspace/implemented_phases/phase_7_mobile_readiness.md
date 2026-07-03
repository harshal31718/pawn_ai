# PAWN — Mobile Readiness Plan (v3)

**Scope:** Minor polish pass for Chrome on mobile. Not a full native-app UX overhaul.
No iOS/Android-specific handling — standard CSS + Tailwind responsive adjustments only.

---

## What Already Works

- Auto-resizing textarea (pill→card morph)
- Floating bottom input with gradient flush
- Sidebar defaults closed on mobile, opens as overlay drawer with backdrop
- Hamburger button on `md:hidden`
- Stop-generation button
- Conversation list scrolls independently

---

## Fixes to Make

| # | Issue | Fix | Effort |
|---|-------|-----|--------|
| 1 | **User bubble too narrow** — `max-w-[50%]` is cramped on small screens | Change to `max-w-[70%] sm:max-w-[50%]` | Trivial |
| 2 | **Hamburger hit area too small** — icon-only button is hard to tap | Add `p-3` so the hit area is at least 44×44px | Trivial |
| 3 | **Delete confirmation buttons too small** — "No"/"Yes" at `text-[10px]` | Bump to `text-sm h-8 min-w-[48px]` | Small |
| 4 | **Conversation search disabled** — input is `cursor-not-allowed` | Remove `disabled`, filter on `title.toLowerCase().includes(query)` | Small |
| 5 | **Trace row wraps badly** — provider badge + agent toggle on one line breaks on narrow screens | Wrap with `flex-wrap` so badge and toggle stack naturally | Trivial |
| 6 | **Code blocks unreadable** — `text-xs` is too small on a phone screen | Bump inline code to `text-sm` on mobile | Trivial |
| 7 | **Bubble color swatches hard to tap** — `w-5 h-5` (20px) in settings | Increase to `w-8 h-8`, wrap to 2 rows of 5 | Small |

---

## Out of Scope

- Virtual keyboard / `visualViewport` handling — Chrome handles this reasonably; not worth the complexity.
- Swipe gestures (sidebar open/close, swipe-to-delete) — deferred, not minor.
- Safe-area-inset / notch handling — Chrome on Android doesn't need it; not targeting iPhone.
- Long-press copy on messages — browser default handles text selection fine.
- `touchmove` on the grid background — cosmetic, not worth it.
- `alert()` replacement in settings — low frequency action, fine as-is.

---

## Priority Order

1. #2 Hamburger hit area — one line change, high impact
2. #3 Delete confirmation size — safety fix
3. #1 User bubble width — one CSS class change
4. #4 Conversation search — small logic addition
5. #5 Trace row wrapping — one class change
6. #6 Code block font size — one class change
7. #7 Color swatch size — small CSS change
