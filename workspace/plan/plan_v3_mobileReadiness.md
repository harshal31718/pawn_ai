# PAWN — Mobile Readiness Plan (v3)

**Author:** Professional UX Audit
**Date:** 2026-06-27
**Scope:** Chatting experience only — normal chat, multiple chats, settings. Excludes account setup, API integration, authentication.

---

## 1. NORMAL CHATTING

### ✅ What Works
- Auto-resizing textarea (pill→card morph) with 138px max-height
- Floating bottom input with gradient flush prevents content from hiding behind it
- Scrollbars hidden globally — clean look on mobile
- User bubbles `max-w-[50%]` keep them compact; assistant bubbles `max-w-[85%]` give reading room
- Stop-generation spinner button (good tactile feedback)
- `Shift+Enter` for newlines respected

### ❌ Issues & Solutions

| # | Issue | Severity | Solution |
|---|-------|----------|----------|
| 1 | **Virtual keyboard hides the input** — No `visualViewport` API integration. On iOS Safari, the fixed bottom input can be pushed behind or above the keyboard unpredictably because the app doesn't listen to `visualViewport.height` changes. | High | Add a `useVisualViewport` hook that measures `window.visualViewport.height` on resize and applies a bottom offset to the input container. On mobile, switch the input from `position: absolute` bottom-flush to `position: fixed` bottom with keyboard-aware padding. |
| 2 | **User bubble `max-w-[50%]` is too narrow on small screens** — On a 375px iPhone SE, that's ~172px of usable text width. Multi-line user messages look cramped and break awkwardly. | Medium | Increase to `max-w-[70%] sm:max-w-[50%]` so on small screens user bubbles get more breathing room. |
| 3 | **No touch feedback on long-press** — Messages don't support long-press to copy text. Mobile users expect this for any selectable text bubble. | Medium | Add `onContextMenu` / `onTouchEnd` with a long-press timer that shows a native "Copy" action. Use `user-select: text` on message content (currently likely `select-none`). |
| 4 | **Trace/metadata row is dense** — Provider badge + "Agent Execution (N steps)" toggle in one row. On 375px width, the provider badge truncates or the text wraps awkwardly. | Low | Stack vertically on mobile: provider badge on its own line, toggle below. |
| 5 | **Streaming cursor (blinking pulse) may flicker on low-refresh-rate phones** — The `animate-pulse` at 1s interval on a thin `w-0.5` element is barely visible. | Low | Increase cursor width to `w-[2px]` and use a smoother opacity animation (`1s` → `0.8s` cubic-bezier). |

---

## 2. MULTIPLE CHATS (Sidebar + Conversation Management)

### ✅ What Works
- Sidebar defaults **closed** on mobile (`innerWidth < 768`) — correct default
- Opens as a **fixed overlay drawer** with `z-50` and `shadow-2xl`
- Dark backdrop (`bg-black/60`) with tap-to-close
- Hamburger button only visible on `md:hidden`
- Inline delete confirmation with outside-tap dismissal
- Conversation list scrolls independently

### ❌ Issues & Solutions

| # | Issue | Severity | Solution |
|---|-------|----------|----------|
| 6 | **No swipe gesture to open/close sidebar** — Users must tap the tiny hamburger icon (top-left, maybe hard to reach on large phones). No swipe-from-left-edge gesture exists. | High | Add edge-swipe detection on the left 20px of the viewport. Use `onTouchStart`/`onTouchMove` to track horizontal drag. Open drawer when swipe exceeds 60px threshold. Also add swipe-right-to-close on the drawer itself (like iOS Mail). |
| 7 | **Hamburger button touch target is small** — It's rendered as a simple icon button. If it inherits `h-5 w-5` or similar, it's below the 44x44px Apple HIG minimum. | High | Ensure hamburger hit area is at least `min-w-[44px] min-h-[44px]`. Use `p-3` or a transparent `::before` pseudo-element extending the hit area. |
| 8 | **Delete confirmation buttons "No"/"Yes" are tiny** — `text-[10px]` with minimal padding. These are ~20px touch targets on a destructive action — a fat-finger accident waiting to happen. | Critical | Replace inline inline confirmation with a **bottom sheet** or **native confirm dialog**. At minimum, use `h-8 min-w-[48px]` buttons with `text-sm`. The current implementation violates all mobile accessibility guidelines for destructive actions. |
| 9 | **No swipe-to-delete on conversation list** — iOS users expect to swipe left on a thread to reveal "Delete". Currently requires 3 taps (open sidebar → tap rename/delete → confirm). | Medium | Add `onTouchStart`/`onTouchMove` for horizontal swipe on conversation items. Show a red "Delete" button behind the swipe (standard iOS pattern). Use `-translate-x` transform for the reveal. |
| 10 | **Conversation list has no search** — Search input exists but is disabled (`cursor-not-allowed`). Users with 20+ conversations on mobile cannot filter. | Medium | Enable search. At minimum filter on `title.toLowerCase().includes(query)`. The input is already in the UI — just remove the `disabled` prop and add filtering logic. |
| 11 | **No empty-state guidance on mobile** — When sidebar opens with no conversations, it shows an icon + text. This is fine but doesn't tell mobile users how to start. | Low | Add a brief hint: "Tap + to start a new chat" below the empty state. |

---

## 3. SETTINGS CHANGES

### ✅ What Works
- Full-page overlay replacing the chat area (clean, no navigation confusion)
- Scrollable content with `max-w-lg` centering
- Theme toggle (System/Light/Dark) works immediately
- Color pickers are visual and responsive to tap

### ❌ Issues & Solutions

| # | Issue | Severity | Solution |
|---|-------|----------|----------|
| 12 | **Bubble color swatches are 20x20px** — `w-5 h-5` is below the 44px touch target minimum. On a 375px screen, 10 swatches in a row are 20px + 4px gaps ≈ 236px wide. They fit but are hard to tap precisely. | Medium | Increase to `w-8 h-8` (32px) minimum. Wrap to 2 rows (5 per row) instead of 1 row of 10. Add a subtle `active:scale-90` tap effect. |
| 13 | **Display name save button may be missed** — User types name but the Save button is a small button next to the input. On mobile, users expect auto-save on blur or a more prominent CTA. | Low | Auto-save on blur (`onBlur` → `localStorage.setItem`). Keep the Save button as a visible secondary option. |
| 14 | **"Clear all data" uses `alert()`** — The confirmation uses `window.alert()` which on mobile shows a browser-native dialog. While functional, it's inconsistent with the app's design language and feels jarring. | Low | Replace with an inline confirmation panel (like the delete conversation pattern) or a simple modal overlay matching the app theme. |
| 15 | **Settings are deep — one-level back only** — The only way out is the back arrow (top-left). On mobile, users may also expect a swipe-right gesture to go back (common iOS pattern). | Low | Add `onTouchEnd` right-swipe gesture on the settings container to navigate back. Or use `react-router` (if/when routing is added) for native back-button support. |
| 16 | **Default Model dropdown is a native `<select>`** — This works fine on mobile (triggers the OS picker) but the options may show provider+model strings that are very long and hard to read in the native picker. | Low | Consider a custom bottom-sheet picker that groups models like the ModelSwitcher does, but only if this becomes a frequently-used setting. Fine to defer. |

---

## 4. CROSS-CUTTING CONCERNS

| # | Issue | Severity | Solution |
|---|-------|----------|----------|
| 17 | **InteractiveGridBackground doesn't respond to touch** — Uses `mousemove` only. On touch devices, the ghost bounces around but doesn't follow the finger. The canvas is `pointer-events-none` so it blocks nothing, but the visual effect is disconnected from user interaction. | Low | Add `touchmove` handler that mirrors the `mousemove` logic. Use `e.touches[0].clientX/Y`. Disable ghost animation when touch is active. |
| 18 | **No safe-area-inset handling** — The app doesn't account for `env(safe-area-inset-bottom)` and `env(safe-area-inset-top)`. On iPhone X+ and modern Android devices, the floating input may sit behind the home indicator. | Medium | Add `pb-[env(safe-area-inset-bottom)]` to the input container. Add `pt-[env(safe-area-inset-top)]` to the header. Use `@supports(padding: env(safe-area-inset-bottom))` to avoid breaking older browsers. |
| 19 | **No orientation lock consideration** — The app uses `overflow-hidden` on the root. If a user rotates to landscape on a phone, the sidebar + chat layout may become extremely narrow or the input bar may be squeezed. | Low | In landscape mode on small screens, consider auto-expanding the sidebar as a persistent side panel (more horizontal space) or increasing the input bar height. |
| 20 | **Font size is not scaled for readability** — The app uses Tailwind defaults (`text-base` = 16px). On mobile, 16px for chat text is acceptable, but code blocks in `text-xs` may be hard to read. | Low | Set `body` font-size to 16px (mobile default for preventing zoom) and bump code blocks to `text-sm` on mobile. |

---

## 5. PRIORITY FIX LIST

| Priority | Issue | Effort |
|----------|-------|--------|
| 🔴 P0 | **Virtual keyboard overlap (#1)** — Input hidden on iOS Safari | Medium (hook + CSS) |
| 🔴 P0 | **Delete confirmation tiny buttons (#8)** — Destructive action risk | Small (bottom sheet or resize) |
| 🔴 P0 | **Hamburger touch target too small (#7)** — Hard to open sidebar | Trivial (extend hit area) |
| 🟡 P1 | **No swipe gesture for sidebar (#6)** — Friction to navigate | Medium (touch handlers) |
| 🟡 P1 | **Safe-area-inset not handled (#18)** — UI behind notches/home indicator | Small (CSS env vars) |
| 🟡 P1 | **Bubble colors too small (#12)** — Hard to tap precisely | Small (resize + wrap) |
| 🟢 P2 | **No long-press copy on messages (#3)** — Missing expected mobile feature | Medium (long-press timer) |
| 🟢 P2 | **No swipe-to-delete conversations (#9)** — Extra taps for common action | Medium (swipe gesture) |
| 🟢 P2 | **User bubble width too narrow (#2)** | Trivial (CSS change) |
| 🟢 P2 | **Conversation search disabled (#10)** | Small (enable + filter) |

---

## 6. MOBILE READINESS SCORE

**Overall: 6/10**

The app has a solid responsive foundation (sidebar overlay, floating input, gradient flushes, scrollbar hiding) but lacks the **gesture-driven, keyboard-aware** polish that mobile users expect from a chat app in 2026. The critical issues are the virtual keyboard overlap (breaks the core chat flow) and the dangerously small delete confirmation targets. Fixing those two alone would bring it to an 8/10.
