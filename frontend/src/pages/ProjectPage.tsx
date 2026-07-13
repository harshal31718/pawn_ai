import { useParams, useOutletContext, useNavigate } from 'react-router-dom'
import { ChatBubbleIcon, FolderIcon, PencilIcon } from '../components/icons'
import type { LayoutContext } from './Layout'

/** Project landing page: name header + its chat list + new-chat-in-project.
 *  Selecting a chat routes to /project/:projectId/chat/:id (ChatPage). */
export default function ProjectPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { store } = useOutletContext<LayoutContext>()
  const { projects, conversations, createConversation, selectConversation } = store

  const project = projects.find((p) => p.id === projectId)
  const chats = conversations.filter((c) => c.project_id === projectId)

  function handleSelectChat(id: string) {
    selectConversation(id)
    navigate(`/project/${projectId}/chat/${id}`)
  }

  function handleNewChat() {
    if (!projectId) return
    const newId = createConversation(projectId)
    navigate(`/project/${projectId}/chat/${newId}`)
  }

  if (!projectId) return null

  return (
    <div className="flex-1 flex flex-col h-full overflow-y-auto">
      <div className="max-w-2xl w-full mx-auto px-6 py-12">
        <div className="flex items-center gap-3 mb-1">
          <FolderIcon className="w-6 h-6 text-theme-text-muted shrink-0" />
          <h1 className="text-2xl font-semibold text-theme-text truncate">
            {project?.name ?? 'Project'}
          </h1>
        </div>
        <p className="text-xs text-theme-text-muted mb-6">
          Chats in this project share retrieval — anything discussed in one is recallable from the others.
        </p>

        <button
          type="button"
          onClick={handleNewChat}
          className="w-full flex items-center gap-3 px-4 py-3 mb-6 rounded-xl text-sm font-semibold text-theme-text bg-theme-surface border border-theme-border/60 hover:bg-theme-surface-hover transition-all active:scale-98 cursor-pointer shadow-sm"
        >
          <PencilIcon className="w-4 h-4 shrink-0 text-theme-text-muted" />
          New chat in this project
        </button>

        {chats.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-10 text-theme-text-muted select-none">
            <ChatBubbleIcon className="w-6 h-6 opacity-40" />
            <span className="text-xs">No chats in this project yet</span>
          </div>
        ) : (
          <div className="space-y-1">
            {chats.map((chat) => (
              <div
                key={chat.id}
                onClick={() => handleSelectChat(chat.id)}
                className="group flex items-center gap-2.5 px-4 py-3 rounded-xl text-sm font-medium cursor-pointer text-theme-text bg-theme-surface/60 hover:bg-theme-surface-hover border border-transparent hover:border-theme-border/60 transition-all"
              >
                <ChatBubbleIcon className="w-4 h-4 shrink-0 text-theme-text-muted opacity-75" />
                <span className="flex-1 truncate">{chat.title}</span>
                <span className="text-[10px] text-theme-text-muted shrink-0">
                  {new Date(chat.updated_at).toLocaleDateString()}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
