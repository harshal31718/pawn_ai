import { useEffect, useRef, useState } from 'react'
import { Outlet, useNavigate } from 'react-router-dom'
import Sidebar from '../components/Sidebar'
import PasswordNudgeModal from '../components/PasswordNudgeModal'
import InteractiveGridBackground from '../components/InteractiveGridBackground'
import { useAuth } from '../contexts/AuthContext'
import { useAppContext } from '../contexts/AppContext'
import { useConversationStore, type ConversationStore } from '../store/useConversationStore'

export default function Layout() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const { displayName, defaultModel, isDark, setTheme, backgroundEffect } = useAppContext()
  const [isSidebarOpen, setIsSidebarOpen] = useState(() => window.innerWidth >= 768)

  // Login-change plan: one-time-per-login nudge. shownRef resets to false on
  // every fresh mount (i.e. every login -- Layout only mounts under
  // RequireAuth), so it fires once per login exactly, gated on the
  // server-side password_changed flag rather than any localStorage state.
  const [showNudge, setShowNudge] = useState(false)
  const shownRef = useRef(false)
  useEffect(() => {
    if (!shownRef.current && user && user.password_changed === false) {
      shownRef.current = true
      setShowNudge(true)
    }
  }, [user])

  const store = useConversationStore(user?.id ?? null, defaultModel)

  return (
    <div className="flex h-screen w-screen bg-theme-bg text-theme-text overflow-hidden font-sans transition-colors duration-200">
      <Sidebar
        conversations={store.conversations}
        projects={store.projects}
        activeId={store.activeConvId}
        pendingIds={store.pendingIds}
        syncError={store.syncError}
        onSelect={store.selectConversation}
        onCreate={store.createConversation}
        onDelete={store.deleteConversation}
        onRename={store.renameConversation}
        onMoveChatToProject={store.moveChatToProject}
        onRemoveChatFromProject={store.removeChatFromProject}
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        onOpen={() => setIsSidebarOpen(true)}
        displayName={displayName}
        email={user?.email || ''}
      />
      {/* Content area — relative so the global toggle can be absolutely positioned */}
      <div className="flex-1 relative overflow-hidden">
        {/* Site-wide interactive grid background, common to every route
            rendered via Outlet below -- toggled by the single "Background
            effect" switch in Settings. Individual pages must not paint an
            opaque bg over their own root container (see ProvidersPage.tsx/
            SettingsPage.tsx/ImageLabPage.tsx, which had theirs removed) or
            this would be invisible behind them. */}
        {backgroundEffect && <InteractiveGridBackground darkMode={isDark} />}
        {/* Global dark mode toggle (+ admin badge) — visible on every route */}
        <div className="absolute top-4 right-4 z-30 pointer-events-none flex items-center gap-2">
          {/* PAWN 2.0 Phase B: admin badge, same pill-chip visual language as
              SettingsPage.tsx's/ImageLabPage.tsx's floating header chip.
              Purely informational (not a nav control) -- the real gate is
              backend require_admin; this just confirms which account you're
              logged in as. */}
          {user?.is_admin && (
            <button
              type="button"
              onClick={() => navigate('/providers?tab=providers-pool')}
              className="h-7 flex items-center px-3 bg-theme-surface border border-theme-border/60 rounded-xl shadow-md pointer-events-auto text-[11px] font-semibold uppercase tracking-wide text-theme-text-muted hover:text-theme-text transition-colors cursor-pointer select-none"
              title="Go to the Providers page's Admin tab"
            >
              Admin
            </button>
          )}
          <button
            type="button"
            onClick={() => setTheme(isDark ? 'light' : 'dark')}
            className={`group w-7 h-7 rounded-xl shadow-md border transition-all active:scale-95 duration-200 focus:outline-none pointer-events-auto flex items-center justify-center cursor-pointer ${
              isDark
                ? 'bg-theme-surface border-theme-border/60 text-zinc-100 hover:bg-zinc-100 hover:border-zinc-100 hover:text-zinc-900'
                : 'bg-theme-surface border-theme-border/60 text-zinc-900 hover:bg-zinc-900 hover:border-zinc-900 hover:text-zinc-100'
            }`}
            title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {isDark ? (
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-4 h-4 transition-transform duration-300 group-hover:rotate-45">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v2.25m0 13.5V21M5.03 5.03l1.59 1.59m10.76 10.76l1.59 1.59M3 12h2.25m13.5 0H21M5.03 18.97l1.59-1.59m10.76-10.76l1.59-1.59M12 9a3 3 0 100 6 3 3 0 000-6z" />
              </svg>
            ) : (
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-4 h-4 transition-transform duration-300 group-hover:-rotate-12">
                <path strokeLinecap="round" strokeLinejoin="round" d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z" />
              </svg>
            )}
          </button>
        </div>
        <Outlet context={{ isSidebarOpen, setIsSidebarOpen, store }} />
      </div>
      {showNudge && <PasswordNudgeModal onDismiss={() => setShowNudge(false)} />}
    </div>
  )
}

/** Type helper for pages that need the layout context. */
export interface LayoutContext {
  isSidebarOpen: boolean
  setIsSidebarOpen: (open: boolean) => void
  store: ConversationStore
}
