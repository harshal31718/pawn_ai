import { useEffect, useRef, useState } from 'react'
import { useParams, useOutletContext, useNavigate } from 'react-router-dom'
import type { Message } from '../types'
import ChatWindow from '../components/ChatWindow'
import MessageInput from '../components/MessageInput'
import InteractiveGridBackground from '../components/InteractiveGridBackground'
import { useAppContext } from '../contexts/AppContext'
import {
  streamChat,
  uploadDoc,
} from '../api/client'
import { mid } from '../store/ids'
import type { LayoutContext } from './Layout'

export default function ChatPage() {
  const { id: urlConvId, projectId: urlProjectId } = useParams<{ id: string; projectId?: string }>()
  const navigate = useNavigate()
  const { isSidebarOpen, setIsSidebarOpen, store } = useOutletContext<LayoutContext>()
  const {
    isDark,
    availableModels,
    models,
    displayName,
    backgroundEffect,
  } = useAppContext()

  const {
    conversations,
    activeConvId,
    messages,
    streamingConvIds,
    selectConversation,
    createConversation,
    promoteDraft,
    setMessagesFor,
    bumpAfterTurn,
    setStreaming,
    quietTitleRefresh,
  } = store

  // Rate-limit cooldowns are per-conversation (epoch-ms when the lock lifts)
  const [rateLimitUntil, setRateLimitUntil] = useState<Record<string, number>>({})
  const [now, setNow] = useState(() => Date.now())
  const [selectedProvider, setSelectedProvider] = useState('gemini-2.5-flash')

  // Document upload states
  const [attachedDoc, setAttachedDoc] = useState<{ id: string; name: string } | null>(null)
  const [isUploading, setIsUploading] = useState(false)

  // One registry of in-flight streams, keyed by conversation id.
  const streamsRef = useRef<
    Map<string, { assistantId: string; controller: AbortController; userMsgId: string; userContent: string }>
  >(new Map())
  const [draft, setDraft] = useState('')

  // Derived per-active-conversation locks for the composer.
  const isActiveStreaming = activeConvId ? streamingConvIds.has(activeConvId) : false
  const activeRateLimitUntil = activeConvId ? rateLimitUntil[activeConvId] : undefined
  const rateLimitCountdown =
    activeRateLimitUntil && activeRateLimitUntil > now
      ? Math.ceil((activeRateLimitUntil - now) / 1000)
      : null

  // Sync URL → store: when the URL has a conversation id, select it.
  useEffect(() => {
    if (urlConvId && urlConvId !== activeConvId) {
      selectConversation(urlConvId)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlConvId])

  // Sync store → URL: when the active conversation changes in the store (e.g.
  // user clicks a sidebar item, or a chat's scope changes), update the URL to
  // match — routing to /project/:projectId/chat/:id for chats inside a
  // project, /chat/:id for standalone ones.
  useEffect(() => {
    if (!activeConvId) return
    const conv = conversations.find((c) => c.id === activeConvId)
    // An unpromoted draft isn't in `conversations` yet and has no known scope —
    // trust whatever URL got us here (the New Chat / New-chat-in-project
    // handlers already navigate explicitly) rather than bouncing back to
    // /chat/:id before the first send resolves its real scope.
    if (!conv) return
    const targetPath = conv.project_id
      ? `/project/${conv.project_id}/chat/${activeConvId}`
      : `/chat/${activeConvId}`
    const currentPath =
      activeConvId === urlConvId
        ? urlProjectId
          ? `/project/${urlProjectId}/chat/${urlConvId}`
          : `/chat/${urlConvId}`
        : null
    if (targetPath !== currentPath) navigate(targetPath, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeConvId, conversations])

  // When the active conversation changes, sync the model picker to its model
  // and drop any attached document.
  useEffect(() => {
    if (!activeConvId) return
    const conv = conversations.find((c) => c.id === activeConvId)
    if (conv?.model_id) setSelectedProvider(conv.model_id)
    setAttachedDoc(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeConvId])

  // Coerce selected provider when available models change.
  useEffect(() => {
    if (availableModels.length === 0) return
    const ids = availableModels.map((m) => m.model_id)
    if (!ids.includes(selectedProvider)) setSelectedProvider(availableModels[0].model_id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [availableModels, selectedProvider])

  // Tick once a second while any conversation is rate-limited.
  useEffect(() => {
    if (Object.keys(rateLimitUntil).length === 0) return
    const interval = setInterval(() => {
      const t = Date.now()
      setNow(t)
      setRateLimitUntil((prev) => {
        const next: Record<string, number> = {}
        let changed = false
        for (const [cid, until] of Object.entries(prev)) {
          if (until > t) next[cid] = until
          else changed = true
        }
        return changed ? next : prev
      })
    }, 1000)
    return () => clearInterval(interval)
  }, [rateLimitUntil])

  function handleStop() {
    const convId = activeConvId
    if (!convId) return
    const stream = streamsRef.current.get(convId)
    if (!stream) return
    stream.controller.abort()
    setMessagesFor(convId, (prev) =>
      prev.filter((m) => m.id !== stream.assistantId && m.id !== stream.userMsgId),
    )
    setDraft(stream.userContent)
    setStreaming(convId, false)
    streamsRef.current.delete(convId)
  }

  async function handleSend(content: string) {
    if ((activeConvId && streamingConvIds.has(activeConvId)) || isUploading) return

    const convId = activeConvId ?? createConversation()
    promoteDraft(convId)

    // Update URL to the new conversation
    if (!activeConvId) {
      navigate(`/chat/${convId}`, { replace: true })
    }

    const userMsg: Message = { id: mid(), role: 'user', content }
    const assistantId = mid()

    const controller = new AbortController()
    streamsRef.current.set(convId, {
      assistantId,
      controller,
      userMsgId: userMsg.id,
      userContent: content,
    })
    setStreaming(convId, true)

    const history = [...messages, userMsg]
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .map((m) => ({
        role: m.role,
        content: m.content,
      }))

    setMessagesFor(convId, (prev) => [
      ...prev,
      userMsg,
      { id: assistantId, role: 'assistant', content: '' },
    ])

    await streamChat(
      history,
      {
        onRateLimit: (retryAfter) => {
          setStreaming(convId, false)
          streamsRef.current.delete(convId)
          const until = Date.now() + retryAfter * 1000
          setNow(Date.now())
          setRateLimitUntil((prev) => ({ ...prev, [convId]: until }))
        },
        onToken: (delta) => {
          setMessagesFor(convId, (prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: m.content + delta } : m,
            ),
          )
        },
        onDone: (viaProvider) => {
          setMessagesFor(convId, (prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, viaProvider } : m,
            ),
          )
          setStreaming(convId, false)
          streamsRef.current.delete(convId)
          bumpAfterTurn(convId)
          quietTitleRefresh()
        },
        onError: (err) => {
          setMessagesFor(convId, (prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? { ...m, content: `Error: ${err}` }
                : m,
            ),
          )
          setStreaming(convId, false)
          streamsRef.current.delete(convId)
        },
        onStep: (label, detail) => {
          setMessagesFor(convId, (prev) =>
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
        onMemoryHit: (summary, scope, sourceConvId) => {
          setMessagesFor(convId, (prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                  ...m,
                  trace: [
                    ...(m.trace || []),
                    {
                      type: 'memory_hit',
                      summary,
                      scope: scope as 'chat' | 'project' | undefined,
                      sourceConvId,
                      timestamp: new Date().toLocaleTimeString(),
                    },
                  ],
                }
                : m,
            ),
          )
        },
        onModelCall: (model, purpose) => {
          setMessagesFor(convId, (prev) =>
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
        onCitation: (url, title) => {
          setMessagesFor(convId, (prev) =>
            prev.map((m) => {
              if (m.id !== assistantId) return m
              const existing = m.citations || []
              if (existing.some((c) => c.url === url)) return m // de-dup by URL
              return { ...m, citations: [...existing, { url, title }] }
            }),
          )
        },
        onProviderSwitch: (from, to) => {
          const noticeMsg: Message = {
            id: mid(),
            role: 'notice',
            content: `Failing over: ${from} → ${to}`,
          }
          setMessagesFor(convId, (prev) => {
            const idx = prev.findIndex((m) => m.id === assistantId)
            const withNotice = idx !== -1
              ? [...prev.slice(0, idx), noticeMsg, ...prev.slice(idx)]
              : [...prev, noticeMsg]
            return withNotice.map((m) =>
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
            )
          })
        },
      },
      selectedProvider,
      attachedDoc?.id || undefined,
      convId,
      controller.signal,
    )
  }

  async function handleUpload(file: File) {
    setIsUploading(true)
    try {
      // Draft-chat edge (locked rule): promote the draft first, exactly as
      // sending a first message does, so the upload always has a chat to
      // scope its RAG indexing into — no unscoped document rows can exist.
      const convId = activeConvId ?? createConversation()
      promoteDraft(convId)
      if (!activeConvId) {
        navigate(`/chat/${convId}`, { replace: true })
      }
      const docId = await uploadDoc(file, convId)
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
    <div className="flex-1 flex flex-col h-full overflow-hidden relative">
      {backgroundEffect && <InteractiveGridBackground darkMode={isDark} />}
      {/* Top gradient flush */}
      <div className="absolute top-0 left-0 right-0 h-10 z-25 pointer-events-none">
        <div className="absolute inset-0 bg-gradient-to-b from-theme-bg via-theme-bg/85 to-transparent" />
      </div>
      {/* Floating Top Header Area — left island only (toggle is global in Layout) */}
      <header className="absolute top-0 left-0 right-0 z-30 pointer-events-none pt-4 pl-4 pr-4 flex items-center w-full">
        {/* Left Floating Island: Project Name/Chat Title */}
        <div className="flex items-center gap-2 px-3.5 py-1.5 bg-theme-surface border border-theme-border/60 rounded-full shadow-md pointer-events-auto z-20 transition-all">
          {!isSidebarOpen && (
            <button
              type="button"
              onClick={() => setIsSidebarOpen(true)}
              className="md:hidden p-3.5 -m-2 rounded-full text-theme-text-muted hover:bg-theme-bg/50 hover:text-theme-text focus:outline-none transition-colors"
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
      </header>

      <ChatWindow messages={messages} isStreaming={isActiveStreaming} />

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
                    disabled={isActiveStreaming}
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
              {models.length > 0 && availableModels.length === 0 && (
                <button
                  type="button"
                  onClick={() => navigate('/settings')}
                  className="flex items-center gap-2 px-3 py-2 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 text-amber-700 dark:text-amber-300 text-xs font-medium hover:opacity-90 transition-opacity text-left"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4 shrink-0">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm.75-13a.75.75 0 00-1.5 0v5c0 .414.336.75.75h4a.75.75 0 000-1.5h-3.25V5z" clipRule="evenodd" />
                  </svg>
                  No provider keys yet — add one in Settings to choose a model.
                </button>
              )}
              <MessageInput
                value={draft}
                onChange={setDraft}
                onSend={handleSend}
                onStop={handleStop}
                disabled={isActiveStreaming || rateLimitCountdown !== null}
                onUpload={handleUpload}
                isUploading={isUploading}
                selectedProvider={selectedProvider}
                onChangeProvider={setSelectedProvider}
                models={availableModels}
              />
            </div>
          </div>
        </div>
      )}

      {/* Floating Bottom Input Area — only when chat has messages */}
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
                disabled={isActiveStreaming}
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
            value={draft}
            onChange={setDraft}
            onSend={handleSend}
            onStop={handleStop}
            disabled={isActiveStreaming || rateLimitCountdown !== null}
            onUpload={handleUpload}
            isUploading={isUploading}
            selectedProvider={selectedProvider}
            onChangeProvider={setSelectedProvider}
            models={availableModels}
          />
        </div>
      </div>
      )}
    </div>
  )
}
