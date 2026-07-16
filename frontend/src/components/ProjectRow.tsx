import { useEffect, useRef, useState } from 'react'
import type { CachedConversation, CachedProject } from '../types'
import KebabMenu from './KebabMenu'
import { FolderIcon } from './icons'

interface Props {
  project: CachedProject
  chats: CachedConversation[]
  activeProjectId?: string | null
  pendingIds?: Set<string>
  onOpenProject: (projectId: string) => void
  onNewChatInProject: (projectId: string) => void
  onRenameProject: (id: string, name: string) => void
  onRequestDeleteProject: (project: CachedProject, chats: CachedConversation[]) => void
  onClearMemory: (scopeType: 'chat' | 'project', scopeId: string, label: string) => void
  onRebuildMemory: (scopeType: 'chat' | 'project', scopeId: string) => void
}

/** One project row — name + kebab menu only. Chats inside a project are no
 *  longer browsable inline in the sidebar (that expand-in-place list was
 *  removed per user feedback: clicking the project name is the one way in,
 *  landing on ProjectPage where its chats are actually shown). Split out of
 *  Sidebar.tsx per .claude/rules/frontend.md (components over ~150 lines
 *  get split). */
export default function ProjectRow({
  project,
  chats,
  activeProjectId,
  pendingIds,
  onOpenProject,
  onNewChatInProject,
  onRenameProject,
  onRequestDeleteProject,
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
        onClick={() => onOpenProject(project.id)}
        className={`group relative flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold cursor-pointer transition-all ${
          activeProjectId === project.id
            ? 'bg-theme-brand text-theme-brand-text shadow-sm'
            : 'text-theme-text hover:bg-theme-surface-hover'
        }`}
      >
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
            <div className="absolute right-1 top-1/2 -translate-y-1/2 z-50 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
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
    </div>
  )
}
