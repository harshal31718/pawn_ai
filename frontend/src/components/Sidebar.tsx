import { useState, useRef, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import type { CachedConversation, CachedProject } from '../types'
import { clearMemory, rebuildMemory } from '../api/client'
import ConfirmDialog from './ConfirmDialog'
import KebabMenu from './KebabMenu'
import ProjectSection from './ProjectSection'
import SearchResults from './SearchResults'
import SidebarTitleRow from './SidebarTitleRow'
import { SidebarLayoutIcon, PencilIcon, BeakerIcon, MagnifierIcon, SettingsGearIcon, ChatBubbleIcon, GaugeIcon } from './icons'

interface Props {
  conversations: CachedConversation[]
  projects: CachedProject[]
  activeId: string | null
  pendingIds?: Set<string>
  syncError?: string | null
  onSelect: (id: string) => void
  onCreate: (targetProjectId?: string) => string
  onDelete: (id: string) => void
  onRename: (id: string, newTitle: string) => void
  onMoveChatToProject: (convId: string, projectId: string) => void
  onRemoveChatFromProject: (convId: string) => void
  isOpen: boolean
  onClose: () => void
  onOpen: () => void
  displayName: string
  email?: string
}

type PendingDialog =
  | { kind: 'addToProject'; convId: string; convTitle: string; projectId: string; projectName: string }
  | { kind: 'clearMemory'; scopeType: 'chat' | 'project'; scopeId: string; label: string }

export default function Sidebar({
  conversations,
  projects,
  activeId,
  pendingIds,
  syncError,
  onSelect,
  onCreate,
  onDelete,
  onRename,
  onMoveChatToProject,
  onRemoveChatFromProject,
  isOpen,
  onClose,
  onOpen,
  displayName,
  email,
}: Props) {
  const navigate = useNavigate()
  const location = useLocation()
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [chatsCollapsed, setChatsCollapsed] = useState(false)
  const [dialog, setDialog] = useState<PendingDialog | null>(null)
  const [focusSearchPending, setFocusSearchPending] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)

  // The Chats section lists EVERY chat — standalone ones show their bare
  // title, project-attached ones are prefixed "Project / Title" — sorted
  // newest-first. (Previously it filtered to standalone-only, so a chat
  // created inside a project never appeared here at all.)
  const projectNameById = new Map(projects.map((p) => [p.id, p.name]))
  const allConversations = [...conversations].sort(
    (a, b) => (Date.parse(b.updated_at) || 0) - (Date.parse(a.updated_at) || 0),
  )

  const isChatActive = location.pathname.startsWith('/chat/')
  const isImageLabActive = location.pathname === '/imagelab'
  const isProjectsActive = location.pathname.startsWith('/project')
  const isSettingsActive = location.pathname === '/settings'
  const isProvidersActive = location.pathname === '/providers'

  // P.3: search spans everything (standalone + project-scoped chats, and
  // project names themselves) -- it used to only filter standaloneConversations,
  // so a match inside a project was invisible to search entirely.
  const trimmedQuery = query.trim().toLowerCase()
  const isSearching = trimmedQuery.length > 0
  const matchedProjects = isSearching
    ? projects.filter((p) => p.name.toLowerCase().includes(trimmedQuery))
    : []
  const matchedConversations = isSearching
    ? conversations.filter((c) => (c.title || '').toLowerCase().includes(trimmedQuery))
    : []

  function handleRequestClearMemory(scopeType: 'chat' | 'project', scopeId: string, label: string) {
    setDialog({ kind: 'clearMemory', scopeType, scopeId, label })
  }

  function handleRebuildMemory(scopeType: 'chat' | 'project', scopeId: string) {
    rebuildMemory(scopeType, scopeId).catch((err) => alert(`Failed to rebuild memory: ${err.message}`))
  }

  useEffect(() => {
    if (editingId && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [editingId])

  // Clicking Search in the mini rail opens the sidebar AND drops the user
  // straight into typing -- isOpen flips synchronously via the parent, but
  // the <input> only mounts once that re-render lands, so focus has to wait
  // for it rather than firing inline in the click handler.
  useEffect(() => {
    if (isOpen && focusSearchPending) {
      searchInputRef.current?.focus()
      setFocusSearchPending(false)
    }
  }, [isOpen, focusSearchPending])

  const handleOpenToSearch = () => {
    setFocusSearchPending(true)
    onOpen()
  }

  function handleStartRename(conv: CachedConversation, e?: React.MouseEvent) {
    e?.stopPropagation()
    setEditingId(conv.id)
    setEditValue(conv.title)
  }

  function handleSaveRename(id: string) {
    const trimmed = editValue.trim()
    if (trimmed && trimmed !== conversations.find((c) => c.id === id)?.title) {
      onRename(id, trimmed)
    }
    setEditingId(null)
  }

  function handleKeyDown(id: string, e: React.KeyboardEvent) {
    if (e.key === 'Enter') {
      handleSaveRename(id)
    } else if (e.key === 'Escape') {
      setEditingId(null)
    }
  }

  const handleNewChat = () => {
    // Dedupe-to-empty is handled race-free in the store (createConversation),
    // since the optimistic conv is inserted synchronously.
    const newId = onCreate()
    navigate(`/chat/${newId}`)
    onClose()
  }

  const handleImageLab = () => {
    navigate('/imagelab')
    onClose()
  }

  const handleSelectConversation = (id: string) => {
    onSelect(id)
    navigate(`/chat/${id}`)
  }

  const handleSelectProjectChat = (id: string, projectId: string) => {
    onSelect(id)
    navigate(`/project/${projectId}/chat/${id}`)
  }

  const handleOpenProject = (projectId: string) => {
    navigate(`/project/${projectId}`)
  }

  const handleOpenSettings = () => {
    navigate('/settings')
    onClose()
  }

  const handleOpenProviders = () => {
    navigate('/providers')
    onClose()
  }

  function handleAddToProject(convId: string, convTitle: string, projectId: string, projectName: string) {
    setDialog({ kind: 'addToProject', convId, convTitle, projectId, projectName })
  }

  function handleConfirmDialog() {
    if (!dialog) return
    if (dialog.kind === 'addToProject') {
      onMoveChatToProject(dialog.convId, dialog.projectId)
    } else {
      clearMemory(dialog.scopeType, dialog.scopeId).catch((err) =>
        alert(`Failed to clear memory: ${err.message}`),
      )
    }
    setDialog(null)
  }

  return (
    <>
      {/* Mobile Drawer Backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/60 z-40 md:hidden transition-opacity duration-200 animate-in fade-in"
          onClick={onClose}
        />
      )}

      {/* isOpen drives the aside's own width (w-12 <-> w-64). Header and nav
          rows are ONE persistent tree (not two swapping layouts): each
          icon sits at a fixed px-3 inset regardless of isOpen, and only the
          label/title next to it animates width+opacity to 0 -- so opening/
          closing reads as these rows growing/shrinking in place, with zero
          icon position shift, instead of a crossfade between two separate
          layouts. Only the Chats/search scroll region (which has no
          collapsed-rail equivalent) and the footer remain isOpen-only. */}
      <aside className={`
        bg-theme-surface text-theme-text flex flex-col h-full border-r border-theme-border shrink-0 select-none
        transition-all duration-300 ease-in-out overflow-hidden
        ${isOpen
          ? 'fixed inset-y-0 left-0 z-50 w-64 shadow-2xl md:relative md:translate-x-0 md:shadow-none animate-in slide-in-from-left duration-200'
          : 'hidden md:flex md:relative w-12'}
      `}>
        {/* Header — expanded: PAWN on the left, toggle on the right.
            Collapsed: toggle only, top-left (mini rail unchanged). */}
        {isOpen ? (
          <div className="pt-4 px-4 flex items-center justify-between shrink-0">
            <div className="flex items-center gap-2">
              <span className="text-base font-semibold text-theme-text font-sans tracking-tight">PAWN</span>
              <span className="text-[7px] uppercase tracking-[0.15em] text-theme-text-muted border border-theme-border rounded-full px-1 py-0.5">
                Beta
              </span>
            </div>
            <button
              onClick={onClose}
              className="
                w-7 h-7 shrink-0 rounded-xl text-theme-text-muted hover:text-theme-text hover:bg-theme-surface-hover
                transition-all active:scale-95 cursor-pointer flex items-center justify-center
              "
              title="Collapse sidebar"
            >
              <SidebarLayoutIcon className="w-4 h-4" />
            </button>
          </div>
        ) : (
          <div className="pt-4 px-2 flex items-center shrink-0">
            <button
              onClick={onOpen}
              className="
                w-7 h-7 shrink-0 rounded-xl text-theme-text-muted hover:text-theme-text hover:bg-theme-surface-hover
                transition-all active:scale-95 cursor-pointer flex items-center justify-center
              "
              title="Expand sidebar"
            >
              <SidebarLayoutIcon className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* Search / New chat / Image Lab / Projects — icons pinned, labels
            animate via SidebarTitleRow's expanded prop. */}
        <div className="shrink-0" onClick={(e) => {
          if (!isOpen && e.target === e.currentTarget) {
            onOpen()
          }
        }}>
          {isOpen ? (
            <div className="group relative z-0 flex items-center h-7">
              {/* Same boxed hover as the toggle/nav rows -- a tight w-7 box
                  around the icon, not the whole input. */}
              <span className="absolute -z-10 inset-y-0 left-2 w-7 rounded-xl group-hover:bg-theme-surface-hover" />
              <MagnifierIcon className="w-4 h-4 text-theme-text-muted absolute left-3.5 pointer-events-none select-none z-10" />
              <input
                ref={searchInputRef}
                type="text"
                placeholder="Search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="
                  w-full h-7 pl-10 pr-3 rounded-xl text-xs font-semibold
                  text-theme-text placeholder-theme-text placeholder:font-semibold
                  focus:outline-none focus:bg-theme-surface-hover transition-colors
                "
              />
            </div>
          ) : (
            <div className="flex items-center px-2 h-7">
              <button
                type="button"
                onClick={handleOpenToSearch}
                className="group relative w-7 h-7 shrink-0 rounded-xl text-theme-text-muted hover:text-theme-text hover:bg-theme-surface-hover transition-all cursor-pointer flex items-center justify-center"
                title="Search chats"
              >
                <MagnifierIcon className="w-4 h-4" />
              </button>
            </div>
          )}
          <SidebarTitleRow expanded={isOpen} icon={PencilIcon} label="New chat" onClick={handleNewChat} isActive={false} />
          <SidebarTitleRow expanded={isOpen} icon={BeakerIcon} label="Image Lab" onClick={handleImageLab} isActive={isImageLabActive} />
          <ProjectSection expanded={isOpen} onNavigated={onClose} isActive={isProjectsActive} />
          <SidebarTitleRow
            expanded={isOpen}
            icon={ChatBubbleIcon}
            label="Chats"
            onClick={() => {
              if (isOpen) {
                setChatsCollapsed((v) => !v)
              } else {
                setChatsCollapsed(false)
                onOpen()
              }
            }}
            toggle={{ collapsed: chatsCollapsed, onToggle: () => setChatsCollapsed((v) => !v) }}
            isActive={isChatActive}
          />
        </div>

        {isOpen && (isSearching ? (
              <SearchResults
                matchedProjects={matchedProjects}
                matchedConversations={matchedConversations}
                projects={projects}
                activeId={activeId}
                onOpenProject={handleOpenProject}
                onSelectChat={(id, projectId) => {
                  if (projectId) handleSelectProjectChat(id, projectId)
                  else handleSelectConversation(id)
                }}
              />
            ) : (
              <>
                {/* Scroll region for Chats -- the "Chats" header itself now
                    lives in the static top block above (alongside Search/
                    New chat/Image Lab/Projects) so it's visible in the
                    collapsed rail too; this region is just the scrollable
                    conversation list. */}
                <div className="flex-1 min-h-0 overflow-y-auto">

                {/* Conversations List */}
                {!chatsCollapsed && (
                <div className="pb-2">
              {allConversations.length === 0 ? (
                <div className="flex flex-col items-center gap-2 py-8 text-theme-text-muted select-none">
                  <ChatBubbleIcon className="w-6 h-6 opacity-40" />
                  <span className="text-xs">No conversations yet</span>
                  <span className="text-[10px] opacity-60">Click &quot;New chat&quot; to start</span>
                </div>
              ) : (
                allConversations.map((conv) => {
                  const isActive = conv.id === activeId
                  const isEditing = conv.id === editingId
                  const projectName = conv.project_id ? projectNameById.get(conv.project_id) : undefined

                  return (
                    <div
                      key={conv.id}
                      onClick={() => {
                        if (!isEditing) {
                          if (conv.project_id) handleSelectProjectChat(conv.id, conv.project_id)
                          else handleSelectConversation(conv.id)
                        }
                      }}
                      className={`
                        group relative flex items-center gap-2.5 pl-3.5 pr-4 h-6 rounded-xl text-xs font-normal cursor-pointer
                        transition-all select-none
                        ${isActive ? 'bg-black/25 dark:bg-black/40 text-theme-text' : 'text-theme-text-muted hover:text-theme-text hover:bg-theme-surface-hover'}
                      `}
                    >
                      {/* Title — project-attached chats are prefixed with their
                          project name (muted "Project / "); standalone chats show
                          the bare title. */}
                      {isEditing ? (
                        <input
                          ref={inputRef}
                          value={editValue}
                          onChange={(e) => setEditValue(e.target.value)}
                          onBlur={() => handleSaveRename(conv.id)}
                          onKeyDown={(e) => handleKeyDown(conv.id, e)}
                          className="
                            flex-1 bg-theme-bg border border-theme-border rounded px-1.5 py-0.5
                            text-xs text-theme-text focus:outline-none focus:ring-1 focus:ring-theme-border
                          "
                          onClick={(e) => e.stopPropagation()}
                        />
                      ) : (
                        <span className="flex-1 truncate pr-6 select-none" onDoubleClick={(e) => handleStartRename(conv, e)}>
                          {projectName && (
                            <span className="text-theme-text-muted/70">{projectName} / </span>
                          )}
                          {conv.title}
                        </span>
                      )}

                      {/* Pending-sync indicator (op queued, not yet acknowledged) */}
                      {!isEditing && pendingIds?.has(conv.id) && (
                        <span
                          title="Syncing…"
                          className="shrink-0 w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse"
                        />
                      )}

                      {/* Inline Actions (visible on item hover) */}
                      {!isEditing && (
                        deleteConfirmId === conv.id ? (
                          <div
                            onClick={(e) => e.stopPropagation()}
                            className="absolute right-1.5 top-1/2 -translate-y-1/2 flex items-center gap-1 bg-theme-bg border border-theme-border rounded-lg shadow-lg px-1.5 h-7 z-50 animate-in fade-in zoom-in-95 duration-100"
                          >
                            <span className="text-[10px] text-theme-text-muted font-medium select-none pr-0.5">Delete?</span>
                            <button
                              type="button"
                              onClick={() => setDeleteConfirmId(null)}
                              className="px-2 h-5 min-w-[36px] rounded border border-theme-border hover:bg-theme-surface-hover text-theme-text text-[10px] font-semibold transition-colors active:scale-95 cursor-pointer"
                            >
                              No
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                onDelete(conv.id)
                                setDeleteConfirmId(null)
                              }}
                              className="px-2 h-5 min-w-[36px] rounded bg-red-600 hover:bg-red-700 text-white border border-red-700 text-[10px] font-semibold transition-colors active:scale-95 cursor-pointer"
                            >
                              Yes
                            </button>
                          </div>
                        ) : (
                          <div className="absolute right-2.5 top-1/2 -translate-y-1/2 z-0 flex items-center gap-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                            <KebabMenu
                              title="More options"
                              items={[
                                { label: 'Rename', onClick: () => handleStartRename(conv) },
                                conv.project_id
                                  ? {
                                      label: 'Remove from project',
                                      onClick: () => onRemoveChatFromProject(conv.id),
                                    }
                                  : {
                                      label: 'Add to project',
                                      submenu: projects.map((p) => ({
                                        label: p.name,
                                        onClick: () => handleAddToProject(conv.id, conv.title, p.id, p.name),
                                      })),
                                    },
                                {
                                  label: 'Memory',
                                  submenu: [
                                    { label: 'Clear memory', onClick: () => handleRequestClearMemory('chat', conv.id, conv.title) },
                                    { label: 'Rebuild memory index', onClick: () => handleRebuildMemory('chat', conv.id) },
                                  ],
                                },
                                { label: 'Delete', danger: true, onClick: () => setDeleteConfirmId(conv.id) },
                              ]}
                            />
                          </div>
                        )
                      )}
                    </div>
                  )
                })
              )}
                </div>
                )}
                </div>
              </>
            ))}

        {/* Spacer so the footer still pins to the bottom in the collapsed
            rail, where there's no scrollable Chats region above it. Also
            doubles as an "empty space" click target to re-expand the
            sidebar, since the mini rail has no room for its own affordance. */}
        {!isOpen && <div className="flex-1 cursor-pointer" onClick={onOpen} />}

        {/* Offline / unsynced changes banner -- F-8: sits above the profile
            card; only meaningful once the sidebar is open. */}
        {isOpen && syncError && (
          <div className="px-3 pt-2 shrink-0">
            <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700/60 text-amber-700 dark:text-amber-300 text-[10px] font-medium">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse shrink-0" />
              <span className="truncate">{syncError}</span>
            </div>
          </div>
        )}

        {/* Footer — Settings icon and avatar circle stay pinned at the same
            position in both states (same fixed-icon/animated-label pattern
            as the nav rows above); only the "Settings" label and the name/
            email column animate width+opacity. */}
        <div className="border-t border-theme-border/40 pt-2 pb-2 shrink-0 select-none">
          <button
            type="button"
            onClick={handleOpenProviders}
            title={!isOpen ? 'Providers' : undefined}
            className="
              group relative z-0 w-full h-7 flex items-center px-2 rounded-xl text-theme-text-muted hover:text-theme-text
              transition-all active:scale-95 cursor-pointer overflow-hidden
            "
          >
            {/* Same boxed hover as the nav rows -- always a tight w-7 box,
                in both expanded and collapsed states. */}
            <span
              className={`
                absolute -z-10 inset-y-0 left-2 w-7 rounded-xl
                ${isProvidersActive ? 'bg-black/25 dark:bg-black/40' : 'group-hover:bg-theme-surface-hover'}
              `}
            />
            <span className="w-7 h-7 shrink-0 flex items-center justify-center">
              <GaugeIcon className={`w-4 h-4 transition-colors ${isProvidersActive ? 'text-theme-text' : 'group-hover:text-theme-text'}`} />
            </span>
            <span
              className={`
                text-xs font-semibold text-theme-text text-left truncate transition-all duration-300 ease-in-out
                ${isOpen ? 'opacity-100 max-w-[10rem] ml-1' : 'opacity-0 max-w-0 ml-0'}
              `}
            >
              Providers
            </span>
          </button>

          {/* Settings + account info merged into one clickable unit (same
              handler regardless of which row is clicked), but the hover/
              active highlight effect is intentionally scoped to the
              Settings row only -- the account-info row below stays visually
              static on hover, per the user's explicit call. */}
          <button
            type="button"
            onClick={handleOpenSettings}
            title={!isOpen ? 'Settings' : undefined}
            className="group relative z-0 w-full flex flex-col text-theme-text-muted hover:text-theme-text transition-all active:scale-95 cursor-pointer"
          >
            <span className="w-full h-7 flex items-center px-2 rounded-xl overflow-hidden relative z-0">
              {/* Same boxed hover as the nav rows -- always a tight w-7 box,
                  in both expanded and collapsed states. */}
              <span
                className={`
                  absolute -z-10 inset-y-0 left-2 w-7 rounded-xl
                  ${isSettingsActive ? 'bg-black/25 dark:bg-black/40' : 'group-hover:bg-theme-surface-hover'}
                `}
              />
              <span className="w-7 h-7 shrink-0 flex items-center justify-center">
                <SettingsGearIcon className={`w-4 h-4 transition-colors ${isSettingsActive ? 'text-theme-text' : 'group-hover:text-theme-text'}`} />
              </span>
              <span
                className={`
                  text-xs font-semibold text-theme-text text-left truncate transition-all duration-300 ease-in-out
                  ${isOpen ? 'opacity-100 max-w-[10rem] ml-1' : 'opacity-0 max-w-0 ml-0'}
                `}
              >
                Settings
              </span>
            </span>

            <span className="w-full h-9 flex items-center px-2">
              <span className="w-7 h-7 shrink-0 flex items-center justify-center">
                <span className="w-5 h-5 rounded-full bg-theme-brand text-theme-brand-text flex items-center justify-center font-bold text-[10px] shadow-sm select-none">
                  {displayName[0]?.toUpperCase() || 'U'}
                </span>
              </span>
              <span
                className={`
                  flex flex-col min-w-0 overflow-hidden text-left transition-all duration-300 ease-in-out
                  ${isOpen ? 'opacity-100 max-w-[10rem] ml-1' : 'opacity-0 max-w-0 ml-0'}
                `}
              >
                <span className="text-xs font-semibold text-theme-text truncate leading-none mb-1 block">{displayName}</span>
                <span className="text-[10px] text-theme-text-muted truncate leading-none block">{email || 'Signed in'}</span>
              </span>
            </span>
          </button>
        </div>
      </aside>

      {/* Backdrop for closing click-outside on delete confirmation */}
      {deleteConfirmId && (
        <div
          className="fixed inset-0 z-40 bg-transparent"
          onClick={() => setDeleteConfirmId(null)}
        />
      )}

      {/* Blocking confirm dialogs — add-to-project / remove-from-project / delete-project */}
      <ConfirmDialog
        open={dialog?.kind === 'addToProject'}
        title="Add to project"
        message={
          dialog?.kind === 'addToProject' ? (
            <>
              This chat's history becomes part of <strong>{dialog.projectName}</strong>'s shared memory
              — other chats in the project can use it.
            </>
          ) : null
        }
        confirmLabel="Add"
        onConfirm={handleConfirmDialog}
        onCancel={() => setDialog(null)}
      />
      <ConfirmDialog
        open={dialog?.kind === 'clearMemory'}
        title="Clear memory"
        destructive
        message={
          dialog?.kind === 'clearMemory' ? (
            <>
              Deletes all indexed memory for <strong>{dialog.label}</strong>
              {dialog.scopeType === 'project' ? ' and every chat inside it' : ''}, both the search index
              and the underlying record it rebuilds from. This cannot be undone.
            </>
          ) : null
        }
        confirmLabel="Clear"
        onConfirm={handleConfirmDialog}
        onCancel={() => setDialog(null)}
      />
    </>
  )
}
