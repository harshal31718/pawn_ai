# Plan 2 UI — URL-Based Routing & Layout Restructuring

## Objective

Migrate the app from conditional-rendering view-switching (`isSettingsOpen` / `isImageLabOpen` flags
in `AppContent`) to proper URL-based routing with `react-router-dom`. The sidebar stays visible on
every route; navigating between Chat, Image Lab, and Settings changes the URL and lets the browser's
back/forward buttons work.

---

## Current State (what the plan must work around)

- `App.tsx` — one monolithic `AppContent` (~680 lines) owns **all** shared state: theme, models,
  BYOK provider keys, display settings, conversation store bootstrap, streaming/rate-limit locks,
  the draft conversation, attached docs, and the chat send/stop/upload handlers. View-switching is
  three `boolean` flags rendered with `isSettingsOpen ? <SettingsPage …/> : isImageLabOpen ?
  <ImageLabPage …/> : <ChatUI …/>`.
- `Sidebar.tsx` — receives callback props `onOpenSettings` / `onOpenImageLab` / `onSelect` / `onCreate`
  and calls them to trigger state changes in `AppContent`. Has **no** routing awareness.
- `SettingsPage.tsx` — receives **15+ props** drilled from `AppContent` (theme, models, displayName,
  bubble colors, etc.) and an `onClose` prop to dismiss itself.
- `ImageLabPage.tsx` — receives an `onClose` prop.
- `react-router-dom` is **not installed** (verified in `package.json`).
- No `src/pages/` directory exists for `SettingsPage` or `ImageLabPage`.

### Key problems the original plan didn't address

1. **State ownership**: `AppContent` state can't live inside a routed page — it must move to a
   shared context so every route can reach it.
2. **`SettingsPage` prop drilling**: 15+ props can't be passed through a router `<Route>`; they
   must come from context.
3. **Store + URL synchronisation**: The conversation store tracks `activeConvId`; the URL tracks
   `/chat/:id`. Both need to stay in sync without a double source of truth.
4. **Draft conversation**: A new chat (no backend ID yet) lives at `/chat` (no `:id`). It must not
   get its own URL row until the first message is sent.
5. **SPA fallback**: Vite dev server already handles `historyApiFallback` for the dev container;
   document as a prod deployment note, don't block this plan on it.

---

## Architecture After This Plan

```
AuthProvider
  └── AuthGate
        ├── LoginPage       (unauthenticated)
        └── AppStateProvider  (new — cross-route state)
              └── BrowserRouter
                    └── Routes
                          └── <Layout />   (Sidebar + <Outlet />)
                                ├── /           → redirect to /chat
                                ├── /chat       → <ChatPage />  (draft / welcome)
                                ├── /chat/:id   → <ChatPage />  (loads conversation)
                                ├── /imagelab   → <ImageLabPage />
                                └── /settings   → <SettingsPage />
```

---

## Files Touched

| Action | File |
|--------|------|
| CREATE | `frontend/src/contexts/AppStateContext.tsx` |
| CREATE | `frontend/src/components/Layout.tsx` |
| CREATE | `frontend/src/pages/ChatPage.tsx` |
| MODIFY | `frontend/src/App.tsx` |
| MODIFY | `frontend/src/components/Sidebar.tsx` |
| MODIFY | `frontend/src/components/SettingsPage.tsx` |
| MODIFY | `frontend/src/components/ImageLabPage.tsx` |
| INSTALL | `react-router-dom` + `@types/react-router-dom` |

`ImageLabPage.tsx` and `SettingsPage.tsx` **stay in `components/`** — no need to move them;
`ChatPage.tsx` is new and goes in `pages/`.

---

## Implementation Steps

### Step 1 — Install dependencies

```bash
npm install react-router-dom
npm install -D @types/react-router-dom
```

---

### Step 2 — Create `AppStateContext.tsx`

**Purpose:** lift all cross-page shared state out of `AppContent` so every route can read it without
prop drilling.

**State to hold:**
- `theme` / `isDark` / `setTheme`
- `models` (registry) / `availableModels` / `configuredProviders` / `refreshKeys`
- `displayName` / `handleSaveDisplayName`
- `defaultModel` / `handleSaveDefaultModel`
- `userBubbleColor` / `handleChangeUserBubble`
- `aiBubbleColor` / `handleChangeAiBubble`
- `backgroundEffect` / `handleToggleBackgroundEffect`

**State NOT to hold** (stays per-page):
- `messages`, `conversations`, streaming state → `useConversationStore` (already a hook, called
  per consumer with `user.id`)
- `draft`, `attachedDoc`, `rateLimitUntil`, `streamsRef` → `ChatPage` local state
- `isSidebarOpen` → `Layout` local state

**Side effects that move here:** theme sync to `document.documentElement` (`useEffect`), bubble
color CSS var sync (`useEffect`), initial `healthCheck()` + `fetchRegistryModels()` + `getKeys()`
on mount.

**Export:** `AppStateProvider` (component) + `useAppState` (hook, throws if used outside provider).

---

### Step 3 — Create `Layout.tsx`

**Purpose:** persistent shell — sidebar on the left, routed content on the right.

```tsx
// src/components/Layout.tsx
export default function Layout() {
  const { user } = useAuth()
  const { displayName, defaultModel, refreshKeys } = useAppState()
  const { conversations, activeConvId, pendingIds, syncError,
          selectConversation, createConversation, deleteConversation,
          renameConversation } = useConversationStore(user?.id ?? null, defaultModel)
  const navigate = useNavigate()
  const [isSidebarOpen, setIsSidebarOpen] = useState(…)

  return (
    <div className="flex h-screen w-screen …">
      <Sidebar
        conversations={conversations}
        activeId={activeConvId}
        pendingIds={pendingIds}
        syncError={syncError}
        onSelect={(id) => { selectConversation(id); navigate(`/chat/${id}`) }}
        onCreate={() => { createConversation(); navigate('/chat') }}
        onDelete={deleteConversation}
        onRename={renameConversation}
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        onOpen={() => setIsSidebarOpen(true)}
        onOpenSettings={() => navigate('/settings')}
        onOpenImageLab={() => navigate('/imagelab')}
        displayName={displayName}
        email={user?.email || ''}
      />
      <Outlet />
    </div>
  )
}
```

**Note:** `useConversationStore` is called here (not in `ChatPage`) because the sidebar needs the
full conversation list regardless of which page is active. `ChatPage` reads the same store via a
second `useConversationStore` call — the hook is idempotent (Zustand singleton); both calls share
the same store instance.

---

### Step 4 — Create `ChatPage.tsx`

**Purpose:** extract the chat UI from `AppContent`. This is the largest chunk of work.

**What moves here from `AppContent`:**
- All of the current `messages.length === 0` welcome/greeting branch
- The floating header (with dark-mode toggle and sidebar-open button)
- `InteractiveGridBackground`
- `ChatWindow` + `MessageInput` (both variants: welcome and floating-bottom)
- `handleSend`, `handleStop`, `handleUpload`, `handleStop`
- `draft`, `attachedDoc`, `isUploading`, `rateLimitUntil`, `streamsRef`

**URL ↔ store sync:**
```tsx
const { id } = useParams()   // undefined on /chat, a UUID on /chat/:id
const { selectConversation, activeConvId, … } = useConversationStore(…)

useEffect(() => {
  if (id && id !== activeConvId) selectConversation(id)
}, [id])
```

This handles direct URL loads and back/forward navigation — the store's `activeConvId` follows
the URL param.

**Draft convention:** on `/chat` (no `id`), `ChatPage` shows the welcome screen with `createConversation()`
called on first send (via the existing `handleSend` logic that already does `activeConvId ??
createConversation()`). After `promoteDraft`, the URL stays at `/chat` until the user picks the new
conversation from the sidebar (which navigates to `/chat/:id`). This is intentional — we don't
`navigate` inside `handleSend` to avoid a double render; the sidebar row appears via the store and
clicking it navigates.

**Reads from `AppStateContext`:** `isDark`, `backgroundEffect`, `theme`, `setTheme`,
`availableModels`, `selectedProvider` (local state seeded from `defaultModel` and synced to the
active conversation's model).

---

### Step 5 — Refactor `App.tsx`

Remove `AppContent` entirely. `App.tsx` becomes a thin bootstrap:

```tsx
export default function App() {
  return (
    <AuthProvider>
      <AuthGate />
    </AuthProvider>
  )
}

function AuthGate() {
  const { isAuthenticated } = useAuth()
  if (!isAuthenticated) return <LoginPage />
  return (
    <AppStateProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Navigate to="/chat" replace />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/chat/:id" element={<ChatPage />} />
            <Route path="/imagelab" element={<ImageLabPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AppStateProvider>
  )
}
```

---

### Step 6 — Update `Sidebar.tsx`

**Interface changes:**
- Props `onOpenSettings` and `onOpenImageLab` remain (Layout passes `navigate(…)` calls — no
  change to Sidebar's API).
- Add **active route highlighting** for the Image Lab and Settings buttons using `useMatch` or pass
  an `activePage` prop from Layout (simpler, avoids importing router hooks into Sidebar):

```tsx
// In Layout, derive and pass:
const location = useLocation()
const activePage = location.pathname.startsWith('/imagelab') ? 'imagelab'
                 : location.pathname.startsWith('/settings') ? 'settings'
                 : 'chat'

<Sidebar activePage={activePage} … />
```

- Sidebar's **conversation list items** use `onSelect(conv.id)` (unchanged). Active highlighting
  stays `conv.id === activeId` (unchanged — Layout passes `activeConvId` from the store).
- Remove the `onClose()` call inside `handleImageLab` and `handleNewChat` — Layout's `onSelect`
  already closes the sidebar if needed, or leave it as is (mobile UX benefit).

---

### Step 7 — Update `SettingsPage.tsx`

**Remove all drilled props.** Replace with context reads:

```tsx
// Before: receives 15+ props
// After: reads from context
const { theme, setTheme, isDark, displayName, handleSaveDisplayName,
        models, defaultModel, handleSaveDefaultModel, refreshKeys,
        userBubbleColor, handleChangeUserBubble, aiBubbleColor,
        handleChangeAiBubble, backgroundEffect, handleToggleBackgroundEffect,
        conversations } = useAppState()
const { user, logout } = useAuth()
const navigate = useNavigate()
```

**Remove `onClose` prop.** Replace the close button action with `navigate(-1)` (back) or
`navigate('/chat')`.

**`conversations` for the data-export/stats section:** move to the store:
```tsx
const { conversations } = useConversationStore(user?.id ?? null, defaultModel)
```

---

### Step 8 — Update `ImageLabPage.tsx`

**Remove `onClose` prop.** Replace close button:
```tsx
const navigate = useNavigate()
// onClose button → navigate('/chat')
```

---

## Verification

- [ ] `npm run build` passes with zero TypeScript errors
- [ ] `/` redirects to `/chat`
- [ ] Clicking a sidebar conversation navigates to `/chat/:id` and loads messages
- [ ] Browser back/forward moves between conversations correctly
- [ ] `/settings` and `/imagelab` are reachable via sidebar buttons; sidebar remains visible
- [ ] Refreshing `/settings` or `/imagelab` loads the correct page (SPA historyApiFallback works in
      the Vite dev container)
- [ ] New chat (sidebar "New chat") shows the welcome screen at `/chat` with no `:id` in the URL
- [ ] After a first message is sent in a draft, the new conversation appears in the sidebar
- [ ] Theme toggle, bubble colors, display name, BYOK keys all work in Settings (reads from context)
- [ ] Image Lab session/generation flow unchanged

---

## Deferred / Out of Scope

- Search sidebar (`disabled` input): unchanged.
- SPA 404 handling in production Nginx: document in `workspace/decisions/` when deploying.
- URL-synced model picker (`?model=…` query param): future enhancement.
- `selectedProvider` per-conversation URL persistence: deferred (currently stored in the conv meta via the store).
