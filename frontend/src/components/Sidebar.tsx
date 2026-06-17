import { useState, useRef, useEffect } from 'react'
import type { ConversationMeta } from '../api/client'

interface Props {
  conversations: ConversationMeta[]
  activeId: string | null
  onSelect: (id: string) => void
  onCreate: () => void
  onDelete: (id: string) => void
  onRename: (id: string, newTitle: string) => void
}

export default function Sidebar({
  conversations,
  activeId,
  onSelect,
  onCreate,
  onDelete,
  onRename,
}: Props) {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (editingId && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [editingId])

  function handleStartRename(conv: ConversationMeta, e: React.MouseEvent) {
    e.stopPropagation()
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

  return (
    <aside className="w-64 bg-zinc-950 text-zinc-100 flex flex-col h-full border-r border-zinc-800 shrink-0 select-none">
      {/* Header */}
      <div className="p-4 flex items-center justify-between shrink-0">
        <span className="text-sm font-semibold tracking-wider text-zinc-400">PAWN WORKSPACE</span>
        <button
          onClick={onCreate}
          className="
            p-1.5 rounded-lg border border-zinc-700 bg-zinc-900 text-zinc-300 hover:text-white hover:bg-zinc-800 hover:border-zinc-500
            transition-all active:scale-95 cursor-pointer flex items-center justify-center
          "
          title="New conversation"
          id="new-chat-button"
        >
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
        </button>
      </div>

      {/* Conversations List */}
      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-1">
        {conversations.length === 0 ? (
          <div className="text-zinc-500 text-xs text-center py-8">No chats yet.</div>
        ) : (
          conversations.map((conv) => {
            const isActive = conv.id === activeId
            const isEditing = conv.id === editingId

            return (
              <div
                key={conv.id}
                onClick={() => !isEditing && onSelect(conv.id)}
                className={`
                  group relative flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-xs font-medium cursor-pointer
                  transition-all select-none
                  ${isActive 
                    ? 'bg-zinc-800 text-white shadow-sm' 
                    : 'text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200'}
                `}
              >
                {/* Chat Bubble Icon */}
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4 shrink-0 text-zinc-500 group-hover:text-zinc-400">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21.75l2.755-4.133a1.14 1.14 0 01.865-.501 48.172 48.172 0 003.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v5.018z" />
                </svg>

                {/* Title */}
                {isEditing ? (
                  <input
                    ref={inputRef}
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    onBlur={() => handleSaveRename(conv.id)}
                    onKeyDown={(e) => handleKeyDown(conv.id, e)}
                    className="
                      flex-1 bg-zinc-900 border border-zinc-700 rounded px-1.5 py-0.5
                      text-xs text-white focus:outline-none focus:ring-1 focus:ring-zinc-500
                    "
                    onClick={(e) => e.stopPropagation()}
                  />
                ) : (
                  <span className="flex-1 truncate pr-8 select-none" onDoubleClick={(e) => handleStartRename(conv, e)}>
                    {conv.title}
                  </span>
                )}

                {/* Inline Actions (visible on item hover) */}
                {!isEditing && (
                  <div className="absolute right-2.5 top-1/2 -translate-y-1/2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={(e) => handleStartRename(conv, e)}
                      className="p-1 rounded hover:bg-zinc-700 text-zinc-500 hover:text-zinc-300"
                      title="Rename"
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-3.5 h-3.5">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L6.832 19.82a4.5 4.5 0 01-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 011.13-1.897L16.863 4.487zm0 0L19.5 7.125" />
                      </svg>
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        if (confirm('Delete this conversation?')) {
                          onDelete(conv.id)
                        }
                      }}
                      className="p-1 rounded hover:bg-zinc-700 text-zinc-500 hover:text-red-400"
                      title="Delete"
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-3.5 h-3.5">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                      </svg>
                    </button>
                  </div>
                )}
              </div>
            )
          })
        )}
      </div>
    </aside>
  )
}
