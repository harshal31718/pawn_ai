import { useEffect, useRef, useState } from 'react'
import type { CachedConversation, CachedProject } from '../types'
import KebabMenu from './KebabMenu'
import { ChatBubbleIcon, ChevronRightIcon, FolderIcon } from './icons'

interface Props {
  project: CachedProject
  chats: CachedConversation[]
  activeId: string | null
  pendingIds?: Set<string>
  expanded: boolean
  onToggleExpand: () => void
  onSelectChat: (id: string) => void
  onNewChatInProject: (projectId: string) => void
  onRenameProject: (id: string, name: string) => void
  onRequestDeleteProject: (project: CachedProject, chats: CachedConversation[]) => void
  onRequestRemoveChatFromProject: (convId: string, title: string, projectName: string) => void
  onClearMemory: (scopeType: 'chat' | 'project', scopeId: string, label: string) => void
  onRebuildMemory: (scopeType: 'chat' | 'project', scopeId: string) => void
}

/** One project row + its expandable chat list. Split out of Sidebar.tsx per
 *  .claude/rules/frontend.md (components over ~150 lines get split). */
export default function ProjectRow({
  project,
  chats,
  activeId,
  pendingIds,
  expanded,
  onToggleExpand,
  onSelectChat,
  onNewChatInProject,
  onRenameProject,
  onRequestDeleteProject,
  onRequestRemoveChatFromProject,
  onClearMemory,
  onRebuildMemory,
}: Props) {
  const [isEditing, setIsEditing] = useState(false)
  const [editValue, setEditValue] = useState(project.name)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [isEditing])

  function startRename() {
    setEditValue(project.name)
    setIsEditing(true)
  }

  function saveRename() {
    const trimmed = editValue.trim()
    if (trimmed && trimmed !== project.name) onRenameProject(project.id, trimmed)
    setIsEditing(false)
  }

  return (
    <div className="select-none">
      <div
        onClick={onToggleExpand}
        className="group relative flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold cursor-pointer text-theme-text hover:bg-theme-surface-hover transition-all"
      >
        <ChevronRightIcon className={`w-3 h-3 shrink-0 text-theme-text-muted transition-transform ${expanded ? 'rotate-90' : ''}`} />
        <FolderIcon className="w-4 h-4 shrink-0 text-theme-text-muted" />
        {isEditing ? (
          <input
            ref={inputRef}
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onBlur={saveRename}
            onKeyDown={(e) => {
              if (e.key === 'Enter') saveRename()
              else if (e.key === 'Escape') setIsEditing(false)
            }}
            onClick={(e) => e.stopPropagation()}
            className="flex-1 bg-theme-bg border border-theme-border rounded px-1.5 py-0.5 text-xs text-theme-text focus:outline-none focus:ring-1 focus:ring-theme-border"
          />
        ) : (
          <span className="flex-1 truncate pr-6" onDoubleClick={(e) => { e.stopPropagation(); startRename() }}>
            {project.name}
          </span>
        )}
        {!isEditing && (
          <>
            {pendingIds?.has(project.id) && (
              <span title="Syncing…" className="shrink-0 w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
            )}
            <div className="absolute right-1 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity">
              <KebabMenu
                title="Project options"
                items={[
                  { label: 'New chat in project', onClick: () => onNewChatInProject(project.id) },
                  { label: 'Rename', onClick: startRename },
                  {
                    label: 'Memory',
                    submenu: [
                      { label: 'Clear memory', onClick: () => onClearMemory('project', project.id, project.name) },
                      { label: 'Rebuild memory index', onClick: () => onRebuildMemory('project', project.id) },
                    ],
                  },
                  { label: 'Delete project', danger: true, onClick: () => onRequestDeleteProject(project, chats) },
                ]}
              />
            </div>
          </>
        )}
      </div>

      {expanded && (
        <div className="ml-4 pl-2 border-l border-theme-border/40 space-y-0.5">
          {chats.length === 0 ? (
            <div className="px-3 py-1.5 text-[10px] text-theme-text-muted select-none">No chats yet</div>
          ) : (
            chats.map((chat) => {
              const isActive = chat.id === activeId
              return (
                <div
                  key={chat.id}
                  onClick={() => onSelectChat(chat.id)}
                  className={`group relative flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium cursor-pointer transition-all ${
                    isActive
                      ? 'bg-theme-brand text-theme-brand-text shadow-sm'
                      : 'text-theme-text-muted hover:bg-theme-surface-hover hover:text-theme-text'
                  }`}
                >
                  <ChatBubbleIcon className="w-3.5 h-3.5 shrink-0 opacity-75" />
                  <span className="flex-1 truncate pr-6">{chat.title}</span>
                  {pendingIds?.has(chat.id) && (
                    <span title="Syncing…" className="shrink-0 w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                  )}
                  <div className="absolute right-1 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <KebabMenu
                      title="Chat options"
                      items={[
                        {
                          label: 'Remove from project',
                          onClick: () => onRequestRemoveChatFromProject(chat.id, chat.title, project.name),
                        },
                        {
                          label: 'Memory',
                          submenu: [
                            { label: 'Clear memory', onClick: () => onClearMemory('chat', chat.id, chat.title) },
                            { label: 'Rebuild memory index', onClick: () => onRebuildMemory('chat', chat.id) },
                          ],
                        },
                      ]}
                    />
                  </div>
                </div>
              )
            })
          )}
        </div>
      )}
    </div>
  )
}
