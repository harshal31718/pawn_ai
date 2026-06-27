import { useCallback, useEffect, useRef, useState } from 'react'
import type { Message } from './types'
import ChatWindow from './components/ChatWindow'
import MessageInput from './components/MessageInput'
import Sidebar from './components/Sidebar'
import SettingsPage from './components/SettingsPage'
import InteractiveGridBackground from './components/InteractiveGridBackground'
import LoginPage from './pages/LoginPage'
import { AuthProvider, useAuth } from './contexts/AuthContext'
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

function AppContent() {
  const { user, isAuthenticated, logout } = useAuth()
  const [rateLimitCountdown, setRateLimitCountdown] = useState<number | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [selectedProvider, setSelectedProvider] = useState('gemini-2.5-flash')
  const [models, setModels] = useState<RegistryModel[]>([])

  const [conversations, setConversations] = useState<ConversationMeta[]>([])
  const [activeConvId, setActiveConvId] = useState<string | null>(null)

  // Document upload states
  const [attachedDoc, setAttachedDoc] = useState<{ id: string; name: string } | null>(null)
  const [isUploading, setIsUploading] = useState(false)

  // Responsive sidebar, Theme & Settings states
  const [isSidebarOpen, setIsSidebarOpen] = useState(() => window.innerWidth >= 768)
  const [theme, setTheme] = useState<'system' | 'light' | 'dark'>(() => {
    const saved = localStorage.getItem('pawn-theme')
    if (saved === 'light' || saved === 'dark' || saved === 'system') return saved
    return 'system'
  })
  const [isSettingsOpen, setIsSettingsOpen] = useState(false)
  const [displayName, setDisplayName] = useState(() => user?.name || localStorage.getItem('pawn-display-name') || 'User')
  const [defaultModel, setDefaultModel] = useState(() => localStorage.getItem('pawn-default-model') || 'gemini-2.5-flash')
  const [userBubbleColor, setUserBubbleColor] = useState(() => localStorage.getItem('pawn-user-bubble') || '')
  const [aiBubbleColor, setAiBubbleColor] = useState(() => localStorage.getItem('pawn-ai-bubble') || '')
  const [backgroundEffect, setBackgroundEffect] = useState(() => localStorage.getItem('pawn-bg-effect') !== 'false')

  const isDark = theme === 'dark' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)

  const streamingIdRef = useRef<string | null>(null)

  // Sync theme to document element
  useEffect(() => {
    const dark = theme === 'dark' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
    document.documentElement.classList.toggle('dark', dark)
    localStorage.setItem('pawn-theme', theme)
  }, [theme])

  // Sync bubble color CSS vars
  useEffect(() => {
    const el = document.documentElement
    const PRESETS: Record<string, { bg: string; text: string }> = {
      blue: { bg: '#3b82f6', text: '#ffffff' },
      indigo: { bg: '#4f46e5', text: '#ffffff' },
      violet: { bg: '#7c3aed', text: '#ffffff' },
      teal: { bg: '#0d9488', text: '#ffffff' },
      emerald: { bg: '#059669', text: '#ffffff' },
      rose: { bg: '#e11d48', text: '#ffffff' },
      amber: { bg: '#d97706', text: '#ffffff' },
      slate: { bg: '#475569', text: '#ffffff' },
      black: { bg: '#000000', text: '#ffffff' },
      white: { bg: '#ffffff', text: '#000000' },
    }

    const up = PRESETS[userBubbleColor]
    if (up) {
      el.style.setProperty('--theme-user-bubble', up.bg)
      el.style.setProperty('--theme-user-bubble-text', up.text)
    } else {
      el.style.removeProperty('--theme-user-bubble')
      el.style.removeProperty('--theme-user-bubble-text')
    }

    const ap = PRESETS[aiBubbleColor]
    if (ap) {
      el.style.setProperty('--theme-ai-bubble', ap.bg)
      el.style.setProperty('--theme-ai-bubble-text', ap.text)
    } else {
      el.style.removeProperty('--theme-ai-bubble')
      el.style.removeProperty('--theme-ai-bubble-text')
    }
  }, [userBubbleColor, aiBubbleColor])

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
      const newConv = await createConversation(undefined, defaultModel)
      setConversations((prev) => [newConv, ...prev])
      setActiveConvId(newConv.id)
      setMessages([])
      setAttachedDoc(null)
    } catch (err) {
      console.error('Error creating conversation:', err)
    }
  }

  function handleSaveDisplayName(name: string) {
    setDisplayName(name)
    localStorage.setItem('pawn-display-name', name)
  }

  function handleSaveDefaultModel(modelId: string) {
    setDefaultModel(modelId)
    localStorage.setItem('pawn-default-model', modelId)
  }

  function handleChangeUserBubble(id: string) {
    setUserBubbleColor(id)
    localStorage.setItem('pawn-user-bubble', id)
  }

  function handleChangeAiBubble(id: string) {
    setAiBubbleColor(id)
    localStorage.setItem('pawn-ai-bubble', id)
  }

  function handleToggleBackgroundEffect() {
    setBackgroundEffect((v) => {
      localStorage.setItem('pawn-bg-effect', String(!v))
      return !v
    })
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
        onRateLimit: (retryAfter) => {
          setIsStreaming(false)
          streamingIdRef.current = null
          setRateLimitCountdown(retryAfter)
          const interval = setInterval(() => {
            setRateLimitCountdown((prev) => {
              if (prev === null || prev <= 1) { clearInterval(interval); return null }
              return prev - 1
            })
          }, 1000)
        },
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
        onSelect={(id) => { setActiveConvId(id); setIsSettingsOpen(false) }}
        onCreate={() => { handleCreate(); setIsSettingsOpen(false) }}
        onDelete={handleDelete}
        onRename={handleRename}
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        onOpen={() => setIsSidebarOpen(true)}
        onOpenSettings={() => setIsSettingsOpen((v) => !v)}
        displayName={displayName}
      />
      {isSettingsOpen ? (
        <SettingsPage
          onClose={() => setIsSettingsOpen(false)}
          theme={theme}
          onChangeTheme={setTheme}
          isDark={isDark}
          displayName={displayName}
          onSaveDisplayName={handleSaveDisplayName}
          models={models}
          defaultModel={defaultModel}
          onSaveDefaultModel={handleSaveDefaultModel}
          userBubbleColor={userBubbleColor}
          onChangeUserBubble={handleChangeUserBubble}
          aiBubbleColor={aiBubbleColor}
          onChangeAiBubble={handleChangeAiBubble}
          backgroundEffect={backgroundEffect}
          onToggleBackgroundEffect={handleToggleBackgroundEffect}
          conversations={conversations}
        />
      ) : (
        <div className="flex-1 flex flex-col h-full overflow-hidden relative">
          {backgroundEffect && <InteractiveGridBackground darkMode={isDark} />}
          {/* Top gradient flush — sibling to header, no padding, clips to h-16 */}
          <div className="absolute top-0 left-0 right-0 h-10 z-25 pointer-events-none">
            <div className="absolute inset-0 bg-gradient-to-b from-theme-bg via-theme-bg/85 to-transparent" />
          </div>
          {/* Floating Top Header Area */}
          <header className="absolute top-0 left-0 right-0 z-30 pointer-events-none pt-4 pl-4 pr-4 flex items-center justify-between w-full">


            {/* Left Floating Island: Project Name/Chat Title */}
            <div className="flex items-center gap-2 px-3.5 py-1.5 bg-theme-surface border border-theme-border/60 rounded-full shadow-md pointer-events-auto z-20 transition-all">
              {!isSidebarOpen && (
                <button
                  type="button"
                  onClick={() => setIsSidebarOpen(true)}
                  className="md:hidden px-0.5 py-0 rounded-full text-theme-text-muted hover:bg-theme-bg/50 hover:text-theme-text focus:outline-none transition-colors"
                  title="Open sidebar"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
                  </svg>
                </button>
              )}
              <h1 className="text-xs font-semibold text-theme-text truncate max-w-[150px] md:max-w-xs select-none" title={headerTitle}>
                {headerTitle}
              </h1>
            </div>

            {/* Right Floating Island: Dark mode toggle only */}
            <div className="flex items-center gap-2 px-2.5 py-1.5 bg-theme-surface border border-theme-border/60 rounded-full shadow-md pointer-events-auto z-20 transition-all">
              <button
                type="button"
                onClick={() => setTheme(isDark ? 'light' : 'dark')}
                className="p-0.5 rounded-full text-theme-text-muted hover:bg-theme-bg/50 hover:text-theme-text transition-colors focus:outline-none flex items-center justify-center"
                title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
              >
                {isDark ? (
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v2.25m0 13.5V21M5.03 5.03l1.59 1.59m10.76 10.76l1.59 1.59M3 12h2.25m13.5 0H21M5.03 18.97l1.59-1.59m10.76-10.76l1.59-1.59M12 9a3 3 0 100 6 3 3 0 000-6z" />
                  </svg>
                ) : (
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z" />
                  </svg>
                )}
              </button>
            </div>
          </header>

          <ChatWindow messages={messages} isStreaming={isStreaming} />

          {/* Radial glow behind greeting — only when no messages */}
          {messages.length === 0 && (
            <div
              className="absolute inset-0 pointer-events-none z-0"
              style={{
                background: 'radial-gradient(ellipse 80% 55% at 50% 48%, color-mix(in srgb, var(--theme-brand) 25%, transparent), transparent 70%)'
              }}
            />
          )}

          {/* Centered welcome + input when new chat */}
          {messages.length === 0 && (
            <div className="absolute inset-0 z-20 pointer-events-none flex flex-col items-center justify-center">
              <div className="w-full max-w-3xl flex flex-col items-center gap-6 pointer-events-auto px-4">
                {/* Greeting */}
                {(() => {
                  const firstName = displayName.split(' ')[0] || displayName
                  return (
                    <h1 className="text-3xl font-semibold text-theme-text text-center tracking-tight select-none pointer-events-none">
                      Hi, {firstName}. What&apos;s on your mind?
                    </h1>
                  )
                })()}
                <p className="text-sm text-theme-text-muted text-center max-w-sm leading-relaxed select-none pointer-events-none -mt-3">
                  Ask a question, upload a document, or pick a model to get started.
                </p>
                {/* Input area */}
                <div className="w-full flex flex-col gap-2">
                  {attachedDoc && (
                    <div className="flex items-center gap-1.5 bg-theme-surface border border-theme-border rounded-xl px-2.5 py-1 text-xs text-theme-text select-none self-start shadow-md animate-in fade-in zoom-in duration-200">
                      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-3.5 h-3.5 text-theme-text-muted shrink-0">
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
                  {rateLimitCountdown !== null && (
                    <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 text-amber-700 dark:text-amber-300 text-xs font-medium animate-in fade-in">
                      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4 shrink-0">
                        <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm.75-13a.75.75 0 00-1.5 0v5c0 .414.336.75.75h4a.75.75 0 000-1.5h-3.25V5z" clipRule="evenodd" />
                      </svg>
                      Rate limited — retrying in {rateLimitCountdown}s
                    </div>
                  )}
                  <MessageInput
                    onSend={handleSend}
                    disabled={isStreaming || rateLimitCountdown !== null}
                    onUpload={handleUpload}
                    isUploading={isUploading}
                    selectedProvider={selectedProvider}
                    onChangeProvider={setSelectedProvider}
                    models={models}
                  />
                </div>
              </div>
            </div>
          )}

          {/* Floating Bottom Input Area — gradient flush from bottom-0 (only when chat has messages) */}
          {messages.length > 0 && (
          <div className="absolute bottom-0 left-0 right-0 z-20 pointer-events-none flex flex-col items-center bg-gradient-to-t from-theme-bg via-theme-bg/85 to-transparent">
            <div className="w-full max-w-3xl flex flex-col gap-2 pointer-events-auto pb-4 px-4">
              {attachedDoc && (
                <div className="flex items-center gap-1.5 bg-theme-surface border border-theme-border rounded-xl px-2.5 py-1 text-xs text-theme-text select-none self-start shadow-md animate-in fade-in zoom-in duration-200">
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-3.5 h-3.5 text-theme-text-muted shrink-0">
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

              {rateLimitCountdown !== null && (
                <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 text-amber-700 dark:text-amber-300 text-xs font-medium animate-in fade-in">
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4 shrink-0">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm.75-13a.75.75 0 00-1.5 0v5c0 .414.336.75.75.75h4a.75.75 0 000-1.5h-3.25V5z" clipRule="evenodd" />
                  </svg>
                  Rate limited — retrying in {rateLimitCountdown}s
                </div>
              )}
              <MessageInput
                onSend={handleSend}
                disabled={isStreaming || rateLimitCountdown !== null}
                onUpload={handleUpload}
                isUploading={isUploading}
                selectedProvider={selectedProvider}
                onChangeProvider={setSelectedProvider}
                models={models}
              />
            </div>
          </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AuthGate />
    </AuthProvider>
  )
}

function AuthGate() {
  const { isAuthenticated } = useAuth()
  if (!isAuthenticated) return <LoginPage />
  return <AppContent />
}

