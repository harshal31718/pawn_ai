import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { CachedConversation, CachedProject } from '../types'
import ProjectRow from './ProjectRow'
import NewProjectRow from './NewProjectRow'
import { ChevronRightIcon, FolderPlusIcon } from './icons'

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
  const navigate = useNavigate()
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
    <>
      {/* Stacked sticky headers (Sidebar.tsx's Chats header sits right below
          this one, offset by its exact height via top-7) -- this one is the
          topmost, so it pins at top-0 with the higher z-index.
          Deliberately NOT wrapped in a div that only spans the project rows:
          position:sticky only holds an element in place while its own
          containing block is still in the scrollport -- wrapping the header
          in a div that's just as tall as the (short) project list meant the
          header scrolled away the moment that div's bottom edge passed,
          long before the user finished scrolling into the Chats list below.
          Returning a fragment here makes this header (and the divider/rows
          below) direct children of Sidebar.tsx's single shared scroll
          container, whose full height spans every chat row too -- so the
          header now stays pinned for the entire scroll, not just its own
          section's height. */}
      <div className="sticky top-0 z-20 h-7 bg-theme-surface flex items-center justify-between px-1 py-1 mx-2">
        <div className="flex items-center gap-0.5 min-w-0">
          {/* Collapse toggle — split out from the label so the label itself
              can navigate to the Projects gallery page (F-10) without losing
              the sidebar's own collapse affordance. */}
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            className="p-0.5 rounded hover:bg-theme-surface-hover text-theme-text-muted hover:text-theme-text transition-colors shrink-0 cursor-pointer"
            title={collapsed ? 'Expand' : 'Collapse'}
          >
            <ChevronRightIcon className={`w-2.5 h-2.5 transition-transform ${collapsed ? '' : 'rotate-90'}`} />
          </button>
          <button
            type="button"
            onClick={() => navigate('/projects')}
            className="text-[10px] uppercase tracking-wider font-semibold text-theme-text-muted hover:text-theme-text transition-colors cursor-pointer select-none truncate"
            title="View all projects"
          >
            Projects
          </button>
        </div>
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
        // No inner scroll cap here -- Projects is part of Sidebar.tsx's one
        // shared scroll region now (its own header pins at the top, Chats'
        // header stacks in below it), not its own independently-bounded box.
        <div className="space-y-0.5 pl-2 pr-2.5">
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
      <div className="mt-1 pt-1 mb-1 mx-2 border-t border-theme-border/40" />
    </>
  )
}
