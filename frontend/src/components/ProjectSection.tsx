import { useState } from 'react'
import type { CachedConversation, CachedProject } from '../types'
import ProjectRow from './ProjectRow'
import NewProjectRow from './NewProjectRow'
import { FolderPlusIcon } from './icons'

interface Props {
  projects: CachedProject[]
  conversations: CachedConversation[]
  activeId: string | null
  activeProjectId?: string | null
  pendingIds?: Set<string>
  onOpenProject: (projectId: string) => void
  onSelectChat: (id: string) => void
  onCreateProject: (name: string) => void
  onNewChatInProject: (projectId: string) => void
  onRenameProject: (id: string, name: string) => void
  onRequestDeleteProject: (project: CachedProject, chats: CachedConversation[]) => void
  onRequestRemoveChatFromProject: (convId: string, title: string, projectName: string) => void
  onClearMemory: (scopeType: 'chat' | 'project', scopeId: string, label: string) => void
  onRebuildMemory: (scopeType: 'chat' | 'project', scopeId: string) => void
}

/** Collapsible "Projects" block above the flat chat list, one expandable
 *  ProjectRow per project plus a trailing NewProjectRow. Split out of
 *  Sidebar.tsx per .claude/rules/frontend.md (components over ~150 lines get split). */
export default function ProjectSection({
  projects,
  conversations,
  activeId,
  activeProjectId,
  pendingIds,
  onOpenProject,
  onSelectChat,
  onCreateProject,
  onNewChatInProject,
  onRenameProject,
  onRequestDeleteProject,
  onRequestRemoveChatFromProject,
  onClearMemory,
  onRebuildMemory,
}: Props) {
  const [collapsed, setCollapsed] = useState(false)
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())
  const [isCreating, setIsCreating] = useState(false)

  function toggleExpand(id: string) {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function handleCreate(name: string) {
    onCreateProject(name)
    setIsCreating(false)
  }

  return (
    <div className="px-2 pb-1">
      <div className="flex items-center justify-between px-1 py-1">
        <button
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          className="text-[10px] uppercase tracking-wider font-semibold text-theme-text-muted hover:text-theme-text transition-colors cursor-pointer select-none"
        >
          Projects
        </button>
        <button
          type="button"
          onClick={() => {
            setCollapsed(false)
            setIsCreating(true)
          }}
          className="p-1 rounded hover:bg-theme-surface-hover text-theme-text-muted hover:text-theme-text transition-all active:scale-95 cursor-pointer"
          title="New project"
        >
          <FolderPlusIcon className="w-3.5 h-3.5" />
        </button>
      </div>
      {!collapsed && (
        <div className="space-y-0.5">
          {projects.map((project) => (
            <ProjectRow
              key={project.id}
              project={project}
              chats={conversations.filter((c) => c.project_id === project.id)}
              activeId={activeId}
              activeProjectId={activeProjectId}
              pendingIds={pendingIds}
              expanded={expandedIds.has(project.id)}
              onToggleExpand={() => toggleExpand(project.id)}
              onOpenProject={onOpenProject}
              onSelectChat={onSelectChat}
              onNewChatInProject={onNewChatInProject}
              onRenameProject={onRenameProject}
              onRequestDeleteProject={onRequestDeleteProject}
              onRequestRemoveChatFromProject={onRequestRemoveChatFromProject}
              onClearMemory={onClearMemory}
              onRebuildMemory={onRebuildMemory}
            />
          ))}
          <NewProjectRow
            isCreating={isCreating}
            onStartCreate={() => setIsCreating(true)}
            onCreate={handleCreate}
            onCancel={() => setIsCreating(false)}
          />
        </div>
      )}
      <div className="mt-1 pt-1 border-t border-theme-border/40" />
    </div>
  )
}
