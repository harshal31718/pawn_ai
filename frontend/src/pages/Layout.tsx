import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import Sidebar from '../components/Sidebar'
import { useAuth } from '../contexts/AuthContext'
import { useAppContext } from '../contexts/AppContext'
import { useConversationStore, type ConversationStore } from '../store/useConversationStore'

export default function Layout() {
  const { user } = useAuth()
  const { displayName, defaultModel, isDark, setTheme } = useAppContext()
  const [isSidebarOpen, setIsSidebarOpen] = useState(() => window.innerWidth >= 768)

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
        onCreateProject={() => store.createProject()}
        onRenameProject={store.renameProject}
        onDeleteProject={store.deleteProject}
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
        {/* Global dark mode toggle — visible on every route */}
        <div className="absolute top-4 right-4 z-30 pointer-events-none">
          <button
            type="button"
            onClick={() => setTheme(isDark ? 'light' : 'dark')}
            className={`group px-2.5 py-1.5 rounded-full shadow-md border transition-all active:scale-95 duration-200 focus:outline-none pointer-events-auto flex items-center justify-center cursor-pointer ${
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
    </div>
  )
}

/** Type helper for pages that need the layout context. */
export interface LayoutContext {
  isSidebarOpen: boolean
  setIsSidebarOpen: (open: boolean) => void
  store: ConversationStore
}
