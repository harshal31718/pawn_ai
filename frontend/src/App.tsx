import { useEffect, useRef, useState } from 'react'
import type { Message } from './types'
import ChatWindow from './components/ChatWindow'
import MessageInput from './components/MessageInput'
import ModelSwitcher from './components/ModelSwitcher'
import Sidebar from './components/Sidebar'
import SettingsModal from './components/SettingsModal'
import InteractiveGridBackground from './components/InteractiveGridBackground'
import {
  healthCheck,
  streamChat,
  uploadDoc,
  fetchConversations,
  createConversation,
  fetchConversation,
  deleteConversation,
  updateConversationTitle,
  fetchRegistryModels,
  type ConversationMeta,
  type RegistryModel
} from './api/client'

let nextId = 1

export default function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [selectedProvider, setSelectedProvider] = useState('gemini-2.5-flash')
  const [models, setModels] = useState<RegistryModel[]>([])
  
  const [conversations, setConversations] = useState<ConversationMeta[]>([])
  const [activeConvId, setActiveConvId] = useState<string | null>(null)

  // Document upload states
  const [attachedDoc, setAttachedDoc] = useState<{ id: string; name: string } | null>(null)
  const [isUploading, setIsUploading] = useState(false)

  // Responsive sidebar & Theme states
  const [isSidebarOpen, setIsSidebarOpen] = useState(() => window.innerWidth >= 768)
  const [darkMode, setDarkMode] = useState(() => {
    const saved = localStorage.getItem('pawn-theme')
    return saved === 'dark' || (!saved && window.matchMedia('(prefers-color-scheme: dark)').matches)
  })
  const [isSettingsOpen, setIsSettingsOpen] = useState(false)
  const [displayName, setDisplayName] = useState(() => localStorage.getItem('pawn-display-name') || 'Harshal')

  const streamingIdRef = useRef<string | null>(null)

  // Sync theme to document element
  useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add('dark')
      localStorage.setItem('pawn-theme', 'dark')
    } else {
      document.documentElement.classList.remove('dark')
      localStorage.setItem('pawn-theme', 'light')
    }
  }, [darkMode])

  function handleSaveDisplayName(name: string) {
    setDisplayName(name)
    localStorage.setItem('pawn-display-name', name)
  }

  // 1. Initialise on mount
  useEffect(() => {
    healthCheck()
      .then((data) => console.log('Backend:', data))
      .catch((err) => console.error('Backend unreachable:', err))

    // Pull models registry
    fetchRegistryModels()
      .then((data) => {
        setModels(data)
        if (data.length > 0) {
          setSelectedProvider((prev) => {
            if (prev === 'gemini' && data.some((m) => m.model_id === 'gemini-2.5-flash')) {
              return 'gemini-2.5-flash'
            }
            if (!data.some((m) => m.model_id === prev)) {
              const defaultModel = data.find((m) => m.model_id === 'gemini-2.5-flash') || data[0]
              return defaultModel.model_id
            }
            return prev
          })
        }
      })
      .catch((err) => console.error('Failed to fetch registry models:', err))

    // Pull saved chats
    refreshConversations()
  }, [])

  // 2. Load conversation history when selection changes
  useEffect(() => {
    if (!activeConvId) return

    let active = true
    fetchConversation(activeConvId)
      .then((detail) => {
        if (!active) return
        
        // Map backend history to local message model
        const mapped = detail.messages
          .filter((m) => m.role === 'user' || m.role === 'assistant')
          .map((m) => ({
            id: String(nextId++),
            role: m.role as 'user' | 'assistant',
            content: m.content,
          }))
        
        setMessages(mapped)
        setSelectedProvider(detail.meta.model_id || 'gemini-2.5-flash')
        setAttachedDoc(null) // Clear document context on thread switch
      })
      .catch((err) => {
        console.error(`Error loading conversation ${activeConvId}:`, err)
      })

    return () => {
      active = false
    }
  }, [activeConvId])

  async function refreshConversations(selectId?: string) {
    try {
      const list = await fetchConversations()
      setConversations(list)

      if (list.length > 0) {
        const targetId = selectId || activeConvId || list[0].id
        const exists = list.some((c) => c.id === targetId)
        const nextId = exists ? targetId : list[0].id
        setActiveConvId(nextId)
      } else {
        await handleCreate()
      }
    } catch (err) {
      console.error('Error listing conversations:', err)
    }
  }

  async function handleCreate() {
    try {
      const newConv = await createConversation(undefined, selectedProvider)
      setConversations((prev) => [newConv, ...prev])
      setActiveConvId(newConv.id)
      setMessages([])
      setAttachedDoc(null)
    } catch (err) {
      console.error('Error creating conversation:', err)
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteConversation(id)
      const list = conversations.filter((c) => c.id !== id)
      setConversations(list)

      if (activeConvId === id) {
        if (list.length > 0) {
          setActiveConvId(list[0].id)
        } else {
          await handleCreate()
        }
      }
    } catch (err) {
      console.error('Error deleting conversation:', err)
    }
  }

  async function handleRename(id: string, newTitle: string) {
    try {
      await updateConversationTitle(id, newTitle)
      setConversations((prev) =>
        prev.map((c) => (c.id === id ? { ...c, title: newTitle } : c))
      )
    } catch (err) {
      console.error('Error renaming conversation:', err)
    }
  }

  async function handleSend(content: string) {
    if (isStreaming || isUploading) return

    const userMsg: Message = { id: String(nextId++), role: 'user', content }
    const assistantId = String(nextId++)
    streamingIdRef.current = assistantId

    setMessages((prev) => [
      ...prev,
      userMsg,
      { id: assistantId, role: 'assistant', content: '' },
    ])
    setIsStreaming(true)

    // For persistent threads, we send the history which includes the userMsg.
    // The backend loads from disk and appends userMsg itself.
    const history = [...messages, userMsg]
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .map((m) => ({
        role: m.role,
        content: m.content,
      }))

    await streamChat(
      history,
      {
        onToken: (delta) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: m.content + delta } : m,
            ),
          )
        },
        onDone: (viaProvider) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, viaProvider } : m,
            ),
          )
          setIsStreaming(false)
          streamingIdRef.current = null
          // Refresh list to pull updated message count & automatic title after it completes
          setTimeout(() => {
            refreshConversations(activeConvId || undefined)
          }, 800)
        },
        onError: (err) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? { ...m, content: `Error: ${err}` }
                : m,
            ),
          )
          setIsStreaming(false)
          streamingIdRef.current = null
        },
        onStep: (label, detail) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    trace: [
                      ...(m.trace || []),
                      {
                        type: 'step',
                        label,
                        detail,
                        timestamp: new Date().toLocaleTimeString(),
                      },
                    ],
                  }
                : m,
            ),
          )
        },
        onMemoryHit: (summary) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    trace: [
                      ...(m.trace || []),
                      {
                        type: 'memory_hit',
                        summary,
                        timestamp: new Date().toLocaleTimeString(),
                      },
                    ],
                  }
                : m,
            ),
          )
        },
        onModelCall: (model, purpose) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    trace: [
                      ...(m.trace || []),
                      {
                        type: 'model_call',
                        model,
                        purpose,
                        timestamp: new Date().toLocaleTimeString(),
                      },
                    ],
                  }
                : m,
            ),
          )
        },
        onProviderSwitch: (from, to) => {
          const noticeMsg: Message = {
            id: String(nextId++),
            role: 'notice',
            content: `Failing over: ${from} → ${to}`,
          }
          setMessages((prev) => {
            const idx = prev.findIndex((m) => m.id === assistantId)
            if (idx !== -1) {
              const next = [...prev]
              next.splice(idx, 0, noticeMsg)
              return next
            }
            return [...prev, noticeMsg]
          })
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    trace: [
                      ...(m.trace || []),
                      {
                        type: 'provider_switch',
                        from,
                        to,
                        timestamp: new Date().toLocaleTimeString(),
                      },
                    ],
                  }
                : m,
            ),
          )
        },
      },
      selectedProvider,
      attachedDoc?.id || undefined,
      activeConvId || undefined,
    )
  }

  async function handleUpload(file: File) {
    setIsUploading(true)
    try {
      const docId = await uploadDoc(file)
      setAttachedDoc({ id: docId, name: file.name })
    } catch (err: any) {
      alert(`Upload failed: ${err.message}`)
    } finally {
      setIsUploading(false)
    }
  }

  const activeConv = conversations.find((c) => c.id === activeConvId)
  const headerTitle = activeConv ? activeConv.title : 'PAWN Chat'

  return (
    <div className="flex h-screen w-screen bg-theme-bg text-theme-text overflow-hidden font-sans transition-colors duration-200">
      <Sidebar
        conversations={conversations}
        activeId={activeConvId}
        onSelect={setActiveConvId}
        onCreate={handleCreate}
        onDelete={handleDelete}
        onRename={handleRename}
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        onOpen={() => setIsSidebarOpen(true)}
        onOpenSettings={() => setIsSettingsOpen(true)}
        displayName={displayName}
      />
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        darkMode={darkMode}
        onToggleDarkMode={() => setDarkMode((d) => !d)}
        displayName={displayName}
        onSaveDisplayName={handleSaveDisplayName}
      />
      
      <div className="flex-1 flex flex-col h-full overflow-hidden relative">
        <InteractiveGridBackground darkMode={darkMode} />
        {/* Floating Top Header Area */}
        <header className="absolute top-0 left-0 right-0 z-30 pointer-events-none p-4 flex items-center justify-between w-full">
          {/* Corner Gradient Shading Panels (Center clear, smooth corner fade) */}
          <div className="absolute top-0 left-0 w-1/2 h-16 bg-gradient-to-br from-theme-bg via-theme-bg/25 to-transparent pointer-events-none z-10" />
          <div className="absolute top-0 right-0 w-1/2 h-16 bg-gradient-to-bl from-theme-bg via-theme-bg/25 to-transparent pointer-events-none z-10" />

          {/* Left Floating Island: Project Name/Chat Title */}
          <div className="flex items-center gap-2 px-3.5 py-1.5 bg-theme-surface border border-theme-border/60 rounded-full shadow-md pointer-events-auto z-20 transition-all">
            {!isSidebarOpen && (
              <button
                type="button"
                onClick={() => setIsSidebarOpen(true)}
                className="md:hidden p-1 rounded-full text-theme-text-muted hover:bg-theme-bg/50 hover:text-theme-text focus:outline-none transition-colors"
                title="Open sidebar"
              >
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4.5 h-4.5">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
                </svg>
              </button>
            )}
            <h1 className="text-xs font-semibold text-theme-text truncate max-w-[150px] md:max-w-xs select-none" title={headerTitle}>
              {headerTitle}
            </h1>
          </div>
          
          {/* Right Floating Island: Model switcher + Dark mode combined bar */}
          <div className="flex items-center gap-2 px-2.5 py-1.5 bg-theme-surface border border-theme-border/60 rounded-full shadow-md pointer-events-auto z-20 transition-all">
            <ModelSwitcher
              selected={selectedProvider}
              onChange={setSelectedProvider}
              disabled={isStreaming || isUploading}
              models={models}
            />

            <div className="w-px h-4 bg-theme-border/60 shrink-0" />

            <button
              type="button"
              onClick={() => setDarkMode(!darkMode)}
              className="p-1 rounded-full text-theme-text-muted hover:bg-theme-bg/50 hover:text-theme-text transition-colors focus:outline-none flex items-center justify-center"
              title={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {darkMode ? (
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4.5 h-4.5">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v2.25m0 13.5V21M5.03 5.03l1.59 1.59m10.76 10.76l1.59 1.59M3 12h2.25m13.5 0H21M5.03 18.97l1.59-1.59m10.76-10.76l1.59-1.59M12 9a3 3 0 100 6 3 3 0 000-6z" />
                </svg>
              ) : (
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4.5 h-4.5">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z" />
                </svg>
              )}
            </button>
          </div>
        </header>
        
        <ChatWindow messages={messages} isStreaming={isStreaming} />
        
        {/* Floating Bottom Input Area */}
        <div className="absolute bottom-0 left-0 right-0 z-20 pointer-events-none flex flex-col items-center p-4 bg-gradient-to-t from-theme-bg via-theme-bg/85 to-transparent pt-16">
          <div className="w-full max-w-3xl flex flex-col gap-2 pointer-events-auto">
            {attachedDoc && (
              <div className="flex items-center gap-1.5 bg-theme-surface border border-theme-border rounded-xl px-2.5 py-1 text-xs text-theme-text select-none self-start shadow-md animate-in fade-in zoom-in duration-200">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-3.5 h-3.5 text-zinc-500 shrink-0">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                </svg>
                <span className="font-medium truncate max-w-[200px]">{attachedDoc.name}</span>
                <button
                  type="button"
                  onClick={() => setAttachedDoc(null)}
                  disabled={isStreaming}
                  className="ml-1 text-theme-text-muted hover:text-theme-text disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none"
                  title="Remove attachment"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-3.5 h-3.5">
                    <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
                  </svg>
                </button>
              </div>
            )}

            <MessageInput
              onSend={handleSend}
              disabled={isStreaming}
              onUpload={handleUpload}
              isUploading={isUploading}
            />
          </div>
        </div>
      </div>
    </div>
  )
}

