import type { CachedConversation, CachedProject } from '../types'
import { ChatBubbleIcon, FolderIcon } from './icons'

interface Props {
  matchedProjects: CachedProject[]
  matchedConversations: CachedConversation[]
  projects: CachedProject[]
  activeId: string | null
  onOpenProject: (projectId: string) => void
  onSelectChat: (id: string, projectId?: string) => void
}

/** P.3: unified search results spanning both standalone and project-scoped
 *  chats, plus matching project names -- replaces the Projects section +
 *  Chats list while a search query is active. Split out of Sidebar.tsx per
 *  .claude/rules/frontend.md (components over ~150 lines get split). */
export default function SearchResults({
  matchedProjects,
  matchedConversations,
  projects,
  activeId,
  onOpenProject,
  onSelectChat,
}: Props) {
  const projectNameById = new Map(projects.map((p) => [p.id, p.name]))
  const hasResults = matchedProjects.length > 0 || matchedConversations.length > 0

  if (!hasResults) {
    return (
      <div className="flex-1 overflow-y-auto px-2 py-2">
        <div className="flex flex-col items-center gap-2 py-8 text-theme-text-muted select-none">
          <ChatBubbleIcon className="w-6 h-6 opacity-40" />
          <span className="text-xs">No matches</span>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto px-2 py-2 space-y-1">
      {matchedProjects.length > 0 && (
        <>
          <div className="px-1 pt-1 pb-1">
            <span className="text-[10px] uppercase tracking-wider font-semibold text-theme-text-muted select-none">
              Projects
            </span>
          </div>
          {matchedProjects.map((p) => (
            <div
              key={p.id}
              onClick={() => onOpenProject(p.id)}
              className="flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-xs font-semibold cursor-pointer text-theme-text hover:bg-theme-surface-hover transition-all select-none"
            >
              <FolderIcon className="w-4 h-4 shrink-0 text-theme-text-muted" />
              <span className="flex-1 truncate">{p.name}</span>
            </div>
          ))}
        </>
      )}

      {matchedConversations.length > 0 && (
        <>
          <div className="px-1 pt-2 pb-1">
            <span className="text-[10px] uppercase tracking-wider font-semibold text-theme-text-muted select-none">
              Chats
            </span>
          </div>
          {matchedConversations.map((c) => {
            const isActive = c.id === activeId
            const projectName = c.project_id ? projectNameById.get(c.project_id) : undefined
            return (
              <div
                key={c.id}
                onClick={() => onSelectChat(c.id, c.project_id ?? undefined)}
                className={`flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-xs font-medium cursor-pointer transition-all select-none ${
                  isActive
                    ? 'bg-theme-brand text-theme-brand-text shadow-sm'
                    : 'text-theme-text-muted hover:bg-theme-surface-hover hover:text-theme-text'
                }`}
              >
                <ChatBubbleIcon className="w-4 h-4 shrink-0 opacity-75" />
                <span className="flex-1 truncate">{c.title}</span>
                {projectName && (
                  <span className="text-[10px] text-theme-text-muted shrink-0 truncate max-w-[72px]" title={projectName}>
                    {projectName}
                  </span>
                )}
              </div>
            )
          })}
        </>
      )}
    </div>
  )
}
