import { useState } from 'react'
import { useParams, useOutletContext, useNavigate, Link } from 'react-router-dom'
import { ChatBubbleIcon, ChevronRightIcon, FolderIcon } from '../components/icons'
import KebabMenu from '../components/KebabMenu'
import MessageInput from '../components/MessageInput'
import { clearMemory, rebuildMemory } from '../api/client'
import { useAppContext } from '../contexts/AppContext'
import type { LayoutContext } from './Layout'

/** P.4 — project landing page: opens directly into the chat/compose area
 *  (Claude-style: breadcrumb, header, composer, Recents below) instead of a
 *  chat-list-only page. Deliberately lightweight -- it does NOT duplicate
 *  ChatPage's streaming logic. Sending (or attaching a file) here creates a
 *  project-scoped draft chat and navigates to it, handing the pending
 *  message/file to ChatPage via router state; ChatPage sends/uploads it once
 *  mounted. Selecting an existing chat routes to /project/:id/chat/:id
 *  (ChatPage) exactly as before. */
export default function ProjectPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { store } = useOutletContext<LayoutContext>()
  const { projects, conversations, createConversation, renameProject } = store
  const { displayName, availableModels } = useAppContext()

  const [draft, setDraft] = useState('')
  const [selectedProvider, setSelectedProvider] = useState(availableModels[0]?.model_id || 'gemini-2.5-flash')
  const [isEditingName, setIsEditingName] = useState(false)
  const [nameValue, setNameValue] = useState('')

  const project = projects.find((p) => p.id === projectId)
  const chats = conversations
    .filter((c) => c.project_id === projectId)
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())

  if (!projectId) return null

  function handleSelectChat(id: string) {
    navigate(`/project/${projectId}/chat/${id}`)
  }

  function startRename() {
    setNameValue(project?.name ?? '')
    setIsEditingName(true)
  }

  function saveRename() {
    const trimmed = nameValue.trim()
    if (projectId && trimmed && trimmed !== project?.name) renameProject(projectId, trimmed)
    setIsEditingName(false)
  }

  function handleSend(content: string) {
    if (!content.trim()) return
    const newId = createConversation(projectId)
    navigate(`/project/${projectId}/chat/${newId}`, { state: { pendingMessage: content } })
  }

  function handleUpload(file: File) {
    const newId = createConversation(projectId)
    navigate(`/project/${projectId}/chat/${newId}`, {
      state: { pendingMessage: draft.trim() || undefined, pendingUploadFile: file },
    })
  }

  return (
    <div className="flex-1 flex flex-col h-full overflow-y-auto">
      <div className="w-full max-w-2xl mx-auto px-6 pt-16 pb-12">
        {/* Breadcrumb */}
        <div className="flex items-center gap-1 text-xs text-theme-text-muted mb-3 select-none">
          <Link to="/chat" className="hover:text-theme-text transition-colors">
            Chats
          </Link>
          <ChevronRightIcon className="w-3 h-3" />
          <span className="text-theme-text font-medium truncate max-w-[220px]">{project?.name ?? 'Project'}</span>
        </div>

        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <FolderIcon className="w-6 h-6 text-theme-text-muted shrink-0" />
          {isEditingName ? (
            <input
              autoFocus
              value={nameValue}
              onChange={(e) => setNameValue(e.target.value)}
              onBlur={saveRename}
              onKeyDown={(e) => {
                if (e.key === 'Enter') saveRename()
                else if (e.key === 'Escape') setIsEditingName(false)
              }}
              className="flex-1 text-2xl font-semibold bg-theme-bg border border-theme-border rounded-lg px-2 py-0.5 text-theme-text focus:outline-none focus:ring-1 focus:ring-theme-border"
            />
          ) : (
            <h1
              className="flex-1 text-2xl font-semibold text-theme-text truncate cursor-text"
              onDoubleClick={startRename}
            >
              {project?.name ?? 'Project'}
            </h1>
          )}
          <KebabMenu
            title="Project options"
            items={[
              { label: 'Rename', onClick: startRename },
              {
                label: 'Memory',
                submenu: [
                  { label: 'Clear memory', onClick: () => clearMemory('project', projectId).catch((err) => alert(`Failed to clear memory: ${err.message}`)) },
                  { label: 'Rebuild memory index', onClick: () => rebuildMemory('project', projectId).catch((err) => alert(`Failed to rebuild memory: ${err.message}`)) },
                ],
              },
            ]}
          />
        </div>

        {/* Composer — same component ChatPage uses, creates+navigates on first send/upload */}
        <div className="mb-8">
          <MessageInput
            value={draft}
            onChange={setDraft}
            onSend={handleSend}
            onUpload={handleUpload}
            selectedProvider={selectedProvider}
            onChangeProvider={setSelectedProvider}
            models={availableModels}
          />
        </div>

        {/* Recents */}
        <div className="flex items-center justify-between mb-2">
          <span className="text-[10px] uppercase tracking-wider font-semibold text-theme-text-muted select-none">
            Recents
          </span>
        </div>
        {chats.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-10 text-theme-text-muted select-none">
            <ChatBubbleIcon className="w-6 h-6 opacity-40" />
            <span className="text-xs">No chats in this project yet</span>
            <span className="text-[10px] opacity-60">Hi, {displayName.split(' ')[0] || displayName} — start one above</span>
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
