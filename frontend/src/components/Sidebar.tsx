import { useState, useRef, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import type { CachedConversation, CachedProject } from '../types'
import { clearMemory, rebuildMemory } from '../api/client'
import ConfirmDialog from './ConfirmDialog'
import KebabMenu from './KebabMenu'
import ProjectSection from './ProjectSection'
import { SidebarLayoutIcon, PencilIcon, BeakerIcon, MagnifierIcon, SettingsGearIcon, ChatBubbleIcon, FolderIcon } from './icons'

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
  onCreateProject: (name: string) => void
  onRenameProject: (id: string, name: string) => void
  onDeleteProject: (id: string) => void
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
  | { kind: 'removeFromProject'; convId: string; convTitle: string; projectName: string }
  | { kind: 'deleteProject'; project: CachedProject; chats: CachedConversation[] }
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
  onCreateProject,
  onRenameProject,
  onDeleteProject,
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
  // /project/:projectId or /project/:projectId/chat/:id → highlight that project's row
  const activeProjectId = location.pathname.match(/^\/project\/([^/]+)/)?.[1] ?? null
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [dialog, setDialog] = useState<PendingDialog | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const standaloneConversations = conversations.filter((c) => !c.project_id)
  const filteredConversations = query.trim()
    ? standaloneConversations.filter((c) =>
        (c.title || '').toLowerCase().includes(query.trim().toLowerCase())
      )
    : standaloneConversations

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

  const handleNewChatInProject = (projectId: string) => {
    const newId = onCreate(projectId)
    navigate(`/project/${projectId}/chat/${newId}`)
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

  function handleRequestRemoveChatFromProject(convId: string, convTitle: string, projectName: string) {
    setDialog({ kind: 'removeFromProject', convId, convTitle, projectName })
  }

  function handleRequestDeleteProject(project: CachedProject, chats: CachedConversation[]) {
    setDialog({ kind: 'deleteProject', project, chats })
  }

  function handleAddToProject(convId: string, convTitle: string, projectId: string, projectName: string) {
    setDialog({ kind: 'addToProject', convId, convTitle, projectId, projectName })
  }

  function handleConfirmDialog() {
    if (!dialog) return
    if (dialog.kind === 'addToProject') {
      onMoveChatToProject(dialog.convId, dialog.projectId)
    } else if (dialog.kind === 'removeFromProject') {
      onRemoveChatFromProject(dialog.convId)
    } else if (dialog.kind === 'deleteProject') {
      onDeleteProject(dialog.project.id)
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

      <aside className={`
        bg-theme-surface text-theme-text flex-col h-full border-r border-theme-border shrink-0 select-none
        transition-all duration-300 ease-in-out
        ${isOpen 
          ? 'flex fixed inset-y-0 left-0 z-50 w-64 shadow-2xl md:relative md:translate-x-0 md:shadow-none animate-in slide-in-from-left duration-200' 
          : 'hidden md:flex md:relative w-12'}
      `}>
        {isOpen ? (
          /* Full Expanded Sidebar */
          <div className="flex flex-col h-full w-64 shrink-0 overflow-hidden animate-in fade-in duration-200">
            {/* Header */}
            <div className="p-4 flex items-center justify-between shrink-0">
              <div className="flex items-center gap-2">
                <span className="text-base font-semibold text-theme-text font-sans tracking-tight">PAWN</span>
                <span className="text-[9px] uppercase tracking-[0.15em] text-theme-text-muted border border-theme-border rounded-full px-1.5 py-0.5">
                  Beta
                </span>
              </div>
              <button
                onClick={onClose}
                className="
                  p-1.5 rounded-lg text-theme-text-muted hover:text-theme-text hover:bg-theme-bg/50
                  transition-all active:scale-95 cursor-pointer flex items-center justify-center
                "
                title="Collapse sidebar"
              >
                <SidebarLayoutIcon className="w-4.5 h-4.5" />
              </button>
            </div>

            {/* Action Button: New Chat */}
            <div className="px-3 pb-2 shrink-0">
              <button
                onClick={handleNewChat}
                className="
                  w-full flex items-center gap-3 px-3 py-2 rounded-xl text-xs font-semibold
                  text-theme-text bg-theme-bg border border-theme-border/50 hover:bg-theme-surface-hover
                  transition-all active:scale-98 cursor-pointer select-none shadow-sm
                "
                id="new-chat-button"
              >
                <PencilIcon className="w-4 h-4 shrink-0 text-theme-text-muted" />
                <span className="py-1">New chat</span>
              </button>
            </div>

            {/* Action Button: Image Lab (Milestone A.0 — throwaway) */}
            <div className="px-3 pb-2 shrink-0">
              <button
                onClick={handleImageLab}
                className="
                  w-full flex items-center gap-3 px-3 py-2 rounded-xl text-xs font-semibold
                  text-theme-text bg-theme-bg border border-theme-border/50 hover:bg-theme-surface-hover
                  transition-all active:scale-98 cursor-pointer select-none shadow-sm
                "
                id="image-lab-button"
                title="Image Lab (experimental)"
              >
                <BeakerIcon className="w-4 h-4 shrink-0 text-theme-text-muted" />
                <span className="py-1">Image Lab</span>
              </button>
            </div>

            {/* Offline / unsynced changes banner */}
            {syncError && (
              <div className="px-3 pb-2 shrink-0">
                <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700/60 text-amber-700 dark:text-amber-300 text-[10px] font-medium">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse shrink-0" />
                  <span className="truncate">{syncError}</span>
                </div>
              </div>
            )}

            {/* Projects section — above the flat chat list */}
            <ProjectSection
              projects={projects}
              conversations={conversations}
              activeId={activeId}
              activeProjectId={activeProjectId}
              pendingIds={pendingIds}
              onOpenProject={handleOpenProject}
              onSelectChat={(id) => {
                const projectId = conversations.find((c) => c.id === id)?.project_id
                if (projectId) handleSelectProjectChat(id, projectId)
                else handleSelectConversation(id)
              }}
              onCreateProject={onCreateProject}
              onNewChatInProject={handleNewChatInProject}
              onRenameProject={onRenameProject}
              onRequestDeleteProject={handleRequestDeleteProject}
              onRequestRemoveChatFromProject={handleRequestRemoveChatFromProject}
              onClearMemory={handleRequestClearMemory}
              onRebuildMemory={handleRebuildMemory}
            />

            {/* Chats section header — mirrors Projects' muted label styling */}
            <div className="px-3 pt-1 pb-1 shrink-0">
              <span className="text-[10px] uppercase tracking-wider font-semibold text-theme-text-muted select-none">
                Chats
              </span>
            </div>

            {/* Search Option */}
            <div className="px-3 pb-2 shrink-0">
              <div className="relative flex items-center">
                <MagnifierIcon className="w-3.5 h-3.5 text-theme-text-muted absolute left-3 pointer-events-none select-none" />
                <input
                  type="text"
                  placeholder="Search chats"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  className="
                    w-full pl-9 pr-3 py-1.5 rounded-xl text-xs bg-theme-bg border border-theme-border/50 text-theme-text placeholder-theme-text-muted
                    focus:outline-none focus:border-theme-text-muted transition-colors
                  "
                />
              </div>
            </div>

            {/* Conversations List */}
            <div className="flex-1 overflow-y-auto px-2 py-2 space-y-1">
              {filteredConversations.length === 0 ? (
                <div className="flex flex-col items-center gap-2 py-8 text-theme-text-muted select-none">
                  <ChatBubbleIcon className="w-6 h-6 opacity-40" />
                  {query.trim() ? (
                    <span className="text-xs">No matching chats</span>
                  ) : (
                    <>
                      <span className="text-xs">No conversations yet</span>
                      <span className="text-[10px] opacity-60">Click &quot;New chat&quot; to start</span>
                    </>
                  )}
                </div>
              ) : (
                filteredConversations.map((conv) => {
                  const isActive = conv.id === activeId
                  const isEditing = conv.id === editingId

                  return (
                    <div
                      key={conv.id}
                      onClick={() => {
                        if (!isEditing) {
                          handleSelectConversation(conv.id)
                        }
                      }}
                      className={`
                        group relative flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-xs font-medium cursor-pointer
                        transition-all select-none
                        ${isActive 
                          ? 'bg-theme-brand text-theme-brand-text shadow-sm' 
                          : 'text-theme-text-muted hover:bg-theme-surface-hover hover:text-theme-text'}
                      `}
                    >
                      {/* Chat Bubble Icon */}
                      <ChatBubbleIcon className="w-4 h-4 shrink-0 text-theme-text-muted opacity-75" />

                      {/* Title */}
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
                            className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1 bg-theme-bg border border-theme-border rounded-lg shadow-lg px-2 py-1 z-50 animate-in fade-in zoom-in-95 duration-100"
                          >
                            <span className="text-[10px] text-theme-text-muted font-medium select-none pr-0.5">Delete?</span>
                            <button
                              type="button"
                              onClick={() => setDeleteConfirmId(null)}
                              className="px-2 h-8 min-w-[48px] rounded border border-theme-border hover:bg-theme-surface-hover text-theme-text text-sm font-semibold transition-colors active:scale-95 cursor-pointer"
                            >
                              No
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                onDelete(conv.id)
                                setDeleteConfirmId(null)
                              }}
                              className="px-2 h-8 min-w-[48px] rounded bg-red-600 hover:bg-red-700 text-white border border-red-700 text-sm font-semibold transition-colors active:scale-95 cursor-pointer"
                            >
                              Yes
                            </button>
                          </div>
                        ) : (
                          <div className="absolute right-2.5 top-1/2 -translate-y-1/2 z-50 flex items-center gap-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                            <KebabMenu
                              title="More options"
                              items={[
                                { label: 'Rename', onClick: () => handleStartRename(conv) },
                                {
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

            {/* User Profile Card */}
            <div className="p-3 border-t border-theme-border/40 bg-theme-surface/30 flex items-center gap-3 shrink-0 select-none">
              <div className="w-8 h-8 rounded-full bg-theme-brand text-theme-brand-text flex items-center justify-center font-bold text-xs shadow-sm shrink-0">
                {displayName[0]?.toUpperCase() || 'U'}
              </div>
              <div className="flex flex-col min-w-0 flex-1">
                <span className="text-xs font-semibold text-theme-text truncate leading-none mb-1">{displayName}</span>
                <span className="text-[10px] text-theme-text-muted truncate leading-none">{email || 'Signed in'}</span>
              </div>
              <button
                type="button"
                onClick={handleOpenSettings}
                className="text-theme-text-muted hover:text-theme-text p-1 rounded-lg hover:bg-theme-bg/50 transition-colors shrink-0 cursor-pointer"
                title="Settings"
              >
                <SettingsGearIcon className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        ) : (
          /* Mini Collapsed Sidebar (w-12) */
          <div 
            onClick={onOpen}
            className="flex flex-col h-full w-12 items-center py-4 justify-between shrink-0 overflow-hidden cursor-pointer animate-in fade-in duration-200"
          >
            {/* Top Options */}
            <div className="flex flex-col items-center gap-4 w-full px-1">
              {/* 1. Open Sidebar Button */}
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onOpen()
                }}
                className="
                  p-2 rounded-xl text-theme-text-muted hover:text-theme-text hover:bg-theme-bg/50
                  transition-all active:scale-95 cursor-pointer flex items-center justify-center
                "
                title="Expand sidebar"
              >
                <SidebarLayoutIcon className="w-5 h-5" />
              </button>
 
              {/* 2. New Chat Button */}
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  handleNewChat()
                }}
                className="
                  p-2 rounded-xl border border-theme-border/50 bg-theme-bg text-theme-text-muted hover:text-theme-text hover:bg-theme-surface-hover
                  transition-all active:scale-95 cursor-pointer flex items-center justify-center shadow-sm
                "
                title="New chat"
              >
                <PencilIcon className="w-4.5 h-4.5" />
              </button>

              {/* 3. Projects Button — expands sidebar with Projects section visible */}
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onOpen()
                }}
                className="
                  p-2 rounded-xl border border-theme-border/50 bg-theme-bg text-theme-text-muted hover:text-theme-text hover:bg-theme-surface-hover
                  transition-all active:scale-95 cursor-pointer flex items-center justify-center shadow-sm
                "
                title="Projects"
              >
                <FolderIcon className="w-4.5 h-4.5" />
              </button>

              {/* 4. Image Lab Button (Milestone A.0 — throwaway) */}
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  handleImageLab()
                }}
                className="
                  p-2 rounded-xl border border-theme-border/50 bg-theme-bg text-theme-text-muted hover:text-theme-text hover:bg-theme-surface-hover
                  transition-all active:scale-95 cursor-pointer flex items-center justify-center shadow-sm
                "
                title="Image Lab (experimental)"
              >
                <BeakerIcon className="w-4.5 h-4.5" />
              </button>

              {/* 5. Search Chat Option */}
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onOpen()
                }}
                className="
                  p-2 rounded-xl border border-theme-border/50 bg-theme-bg text-theme-text-muted hover:text-theme-text hover:bg-theme-surface-hover
                  transition-all active:scale-95 cursor-pointer flex items-center justify-center shadow-sm
                "
                title="Search chats"
              >
                <MagnifierIcon className="w-4.5 h-4.5" />
              </button>
            </div>
 
            {/* 6. Bottom Settings & Profile Avatar */}
            <div className="w-full flex flex-col items-center gap-3.5 border-t border-theme-border/40 pt-4 pb-1 px-1 shrink-0">
              {/* Settings Button */}
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); handleOpenSettings() }}
                className="
                  text-theme-text-muted hover:text-theme-text p-2 rounded-xl hover:bg-theme-bg/50
                  transition-colors cursor-pointer flex items-center justify-center
                "
                title="Settings"
              >
                <SettingsGearIcon className="w-4.5 h-4.5" />
              </button>

              {/* Profile Avatar Circle */}
              <div
                onClick={(e) => e.stopPropagation()}
                className="w-8 h-8 rounded-full bg-theme-brand text-theme-brand-text flex items-center justify-center font-bold text-xs shadow-sm shrink-0 select-none cursor-default"
                title={displayName}
              >
                {displayName[0]?.toUpperCase() || 'U'}
              </div>
            </div>
          </div>
        )}
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
        open={dialog?.kind === 'removeFromProject'}
        title="Remove from project"
        message={
          dialog?.kind === 'removeFromProject' ? (
            <>
              This chat's memory leaves <strong>{dialog.projectName}</strong>. Note: anything other
              chats already wrote using this chat's info stays in those chats.
            </>
          ) : null
        }
        confirmLabel="Remove"
        onConfirm={handleConfirmDialog}
        onCancel={() => setDialog(null)}
      />
      <ConfirmDialog
        open={dialog?.kind === 'deleteProject'}
        title="Delete project"
        destructive
        message={
          dialog?.kind === 'deleteProject' ? (
            <>
              <p className="mb-2">
                Deletes the project <strong>and all {dialog.chats.length} chat{dialog.chats.length === 1 ? '' : 's'} inside it</strong>,
                including their memory. This cannot be undone.
              </p>
              {dialog.chats.length > 0 && (
                <ul className="list-disc pl-4 space-y-0.5 max-h-32 overflow-y-auto">
                  {dialog.chats.map((c) => (
                    <li key={c.id} className="truncate">{c.title}</li>
                  ))}
                </ul>
              )}
            </>
          ) : null
        }
        confirmLabel="Delete"
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
