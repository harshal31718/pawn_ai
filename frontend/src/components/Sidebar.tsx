import { useState, useRef, useEffect } from 'react'
import type { ConversationMeta } from '../api/client'

interface Props {
  conversations: ConversationMeta[]
  activeId: string | null
  onSelect: (id: string) => void
  onCreate: () => void
  onDelete: (id: string) => void
  onRename: (id: string, newTitle: string) => void
  isOpen: boolean
  onClose: () => void
  onOpen: () => void
  onOpenSettings: () => void
  displayName: string
}

export default function Sidebar({
  conversations,
  activeId,
  onSelect,
  onCreate,
  onDelete,
  onRename,
  isOpen,
  onClose,
  onOpen,
  onOpenSettings,
  displayName,
}: Props) {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)
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

  const handleNewChat = () => {
    const emptyChat = conversations.find((c) => c.message_count === 0)
    if (emptyChat) {
      onSelect(emptyChat.id)
    } else {
      onCreate()
    }
    onClose()
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
              <span className="text-base font-semibold text-theme-text font-sans tracking-tight">PAWN</span>
              <button
                onClick={onClose}
                className="
                  p-1.5 rounded-lg text-theme-text-muted hover:text-theme-text hover:bg-theme-bg/50
                  transition-all active:scale-95 cursor-pointer flex items-center justify-center
                "
                title="Collapse sidebar"
              >
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4.5 h-4.5">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3.75h16.5a1.5 1.5 0 011.5 1.5v13.5a1.5 1.5 0 01-1.5 1.5H3.75a1.5 1.5 0 01-1.5-1.5V5.25a1.5 1.5 0 011.5-1.5zM9 3.75v16.5" />
                </svg>
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
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4 shrink-0 text-theme-text-muted">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
                </svg>
                <span className="py-1">New chat</span>
              </button>
            </div>

            {/* Search Option */}
            <div className="px-3 pb-2 shrink-0">
              <div className="relative flex items-center">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-3.5 h-3.5 text-theme-text-muted absolute left-3 pointer-events-none select-none">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.603 10.603z" />
                </svg>
                <input
                  type="text"
                  placeholder="Search chats"
                  disabled
                  className="
                    w-full pl-9 pr-3 py-1.5 rounded-xl text-xs bg-theme-bg border border-theme-border/50 text-theme-text placeholder-theme-text-muted
                    focus:outline-none cursor-not-allowed opacity-60 select-none
                  "
                />
              </div>
            </div>

            {/* Conversations List */}
            <div className="flex-1 overflow-y-auto px-2 py-2 space-y-1">
              {conversations.length === 0 ? (
                <div className="flex flex-col items-center gap-2 py-8 text-theme-text-muted select-none">
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-6 h-6 opacity-40">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21.75l2.755-4.133a1.14 1.14 0 01.865-.501 48.172 48.172 0 003.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v5.018z" />
                  </svg>
                  <span className="text-xs">No conversations yet</span>
                  <span className="text-[10px] opacity-60">Click &quot;New chat&quot; to start</span>
                </div>
              ) : (
                conversations.map((conv) => {
                  const isActive = conv.id === activeId
                  const isEditing = conv.id === editingId

                  return (
                    <div
                      key={conv.id}
                      onClick={() => {
                        if (!isEditing) {
                          onSelect(conv.id)
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
                      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4 shrink-0 text-theme-text-muted opacity-75">
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
                            flex-1 bg-theme-bg border border-theme-border rounded px-1.5 py-0.5
                            text-xs text-theme-text focus:outline-none focus:ring-1 focus:ring-theme-border
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
                        deleteConfirmId === conv.id ? (
                          <div
                            onClick={(e) => e.stopPropagation()}
                            className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1 bg-theme-bg border border-theme-border rounded-lg shadow-lg px-2 py-1 z-50 animate-in fade-in zoom-in-95 duration-100"
                          >
                            <span className="text-[10px] text-theme-text-muted font-medium select-none pr-0.5">Delete?</span>
                            <button
                              type="button"
                              onClick={() => setDeleteConfirmId(null)}
                              className="px-2 py-0.5 rounded border border-theme-border hover:bg-theme-surface-hover text-theme-text text-[10px] font-semibold transition-colors active:scale-95 cursor-pointer"
                            >
                              No
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                onDelete(conv.id)
                                setDeleteConfirmId(null)
                              }}
                              className="px-2 py-0.5 rounded bg-red-600 hover:bg-red-700 text-white border border-red-700 text-[10px] font-semibold transition-colors active:scale-95 cursor-pointer"
                            >
                              Yes
                            </button>
                          </div>
                        ) : (
                          <div className="absolute right-2.5 top-1/2 -translate-y-1/2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                            <button
                              onClick={(e) => handleStartRename(conv, e)}
                              className="p-1 rounded hover:bg-theme-surface text-theme-text-muted hover:text-theme-text transition-all active:scale-95"
                              title="Rename"
                            >
                              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-3.5 h-3.5">
                                <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L6.832 19.82a4.5 4.5 0 01-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 011.13-1.897L16.863 4.487zm0 0L19.5 7.125" />
                              </svg>
                            </button>
                            <button
                              onClick={(e) => {
                                e.stopPropagation()
                                setDeleteConfirmId(conv.id)
                              }}
                              className="p-1 rounded hover:bg-theme-surface text-theme-text-muted hover:text-red-500 transition-all active:scale-95"
                              title="Delete"
                            >
                              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-3.5 h-3.5">
                                <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                              </svg>
                            </button>
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
                <span className="text-[10px] text-theme-text-muted truncate leading-none">harshal@pawn.ai</span>
              </div>
              <button
                type="button"
                onClick={onOpenSettings}
                className="text-theme-text-muted hover:text-theme-text p-1 rounded-lg hover:bg-theme-bg/50 transition-colors shrink-0 cursor-pointer"
                title="Settings"
              >
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-3.5 h-3.5">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.43l-1.003.828c-.293.241-.438.613-.43.992a7.723 7.723 0 010 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.43l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 010-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.645-.869L9.594 3.94z" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
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
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-5 h-5">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3.75h16.5a1.5 1.5 0 011.5 1.5v13.5a1.5 1.5 0 01-1.5 1.5H3.75a1.5 1.5 0 01-1.5-1.5V5.25a1.5 1.5 0 011.5-1.5zM9 3.75v16.5" />
                </svg>
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
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4.5 h-4.5">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
                </svg>
              </button>
 
              {/* 3. Search Chat Option */}
              <button
                disabled
                onClick={(e) => e.stopPropagation()}
                className="
                  p-2 rounded-xl text-theme-text-muted opacity-60 cursor-not-allowed flex items-center justify-center
                "
                title="Search chats"
              >
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4.5 h-4.5">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.603 10.603z" />
                </svg>
              </button>
            </div>
 
            {/* 4. Bottom Settings & Profile Avatar */}
            <div className="w-full flex flex-col items-center gap-3.5 border-t border-theme-border/40 pt-4 pb-1 px-1 shrink-0">
              {/* Settings Button */}
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); onOpenSettings() }}
                className="
                  text-theme-text-muted hover:text-theme-text p-2 rounded-xl hover:bg-theme-bg/50
                  transition-colors cursor-pointer flex items-center justify-center
                "
                title="Settings"
              >
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4.5 h-4.5">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.43l-1.003.828c-.293.241-.438.613-.43.992a7.723 7.723 0 010 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.43l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 010-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.645-.869L9.594 3.94z" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
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
    </>
  )
}
