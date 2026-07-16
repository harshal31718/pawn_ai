import { useEffect, useRef, useState } from 'react'
import { useParams, useOutletContext, useNavigate, useLocation } from 'react-router-dom'
import type { Message, Segment, TraceEntry } from '../types'
import ChatWindow from '../components/ChatWindow'
import MessageInput from '../components/MessageInput'
import type { Mode } from '../components/ModePicker'
import InteractiveGridBackground from '../components/InteractiveGridBackground'
import { useAppContext } from '../contexts/AppContext'
import {
  streamChat,
  uploadDoc,
} from '../api/client'
import { mid } from '../store/ids'
import type { LayoutContext } from './Layout'

// Phase A / A.8 — a "step" event whose label announces an outbound action
// (a tool call or a subagent delegation) becomes a "running" trace entry that
// later flips to "done" + elapsed ms once the next trace-worthy event lands.
// Must stay in lockstep with client.ts's _TOOL_CALL_LABEL_RE (same two
// prefixes) so onToolCall can resolve a `name` for both tool calls and
// delegations -- a code-reviewer WARN from the A.9 pass caught these drifting.
//
// Known limitation (accepted, live-only, self-corrects on reload): settling
// only the LAST entry assumes at most one is ever "running" at a time. That
// holds for the main agent's own loop, but a "Delegating to X" entry stays
// "running" only until the subagent's own first nested step arrives (tagged
// with the subagent's name, not "main") -- that nested step's settle call
// closes the *outer* delegation entry early, understating its live elapsed
// time for the rest of that turn. The persisted trace is unaffected: the
// backend times the whole delegate_<name> call server-side via
// time.monotonic(), so a reload shows the correct duration.
const TOOL_STEP_RE = /^(Calling|Delegating to) /

function settleRunningTrace(trace: TraceEntry[]): TraceEntry[] {
  if (trace.length === 0) return trace
  const last = trace[trace.length - 1]
  if (last.kind !== 'tool' || last.status !== 'running') return trace
  const elapsedMs = last.startedAt ? Date.now() - last.startedAt : undefined
  return [...trace.slice(0, -1), { ...last, status: 'done', elapsedMs }]
}

function appendTraceEntry(trace: TraceEntry[] | undefined, entry: TraceEntry): TraceEntry[] {
  return [...settleRunningTrace(trace || []), entry]
}

// Phase N — segments mirror of the trace helpers above: an ordered,
// arrival-order list of text/tool-entry segments so Message.tsx can render
// "text, then a tool card, then more text" instead of trace-always-above-
// content. A running tool segment settles (status: 'done' + elapsed) the
// moment the next segment of either kind arrives, exactly like trace's own
// settle-on-next-entry rule.
function settleRunningSegment(segments: Segment[]): Segment[] {
  if (segments.length === 0) return segments
  const last = segments[segments.length - 1]
  if (last.type !== 'tool' || last.entry.status !== 'running') return segments
  const elapsedMs = last.entry.startedAt ? Date.now() - last.entry.startedAt : undefined
  return [...segments.slice(0, -1), { type: 'tool', entry: { ...last.entry, status: 'done', elapsedMs } }]
}

function appendTextSegment(segments: Segment[] | undefined, delta: string): Segment[] {
  const settled = settleRunningSegment(segments || [])
  const last = settled[settled.length - 1]
  if (last && last.type === 'text') {
    return [...settled.slice(0, -1), { type: 'text', content: last.content + delta }]
  }
  return [...settled, { type: 'text', content: delta }]
}

function appendToolSegment(segments: Segment[] | undefined, entry: TraceEntry): Segment[] {
  return [...settleRunningSegment(segments || []), { type: 'tool', entry }]
}

export default function ChatPage() {
  const { id: urlConvId, projectId: urlProjectId } = useParams<{ id: string; projectId?: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const { isSidebarOpen, setIsSidebarOpen, store } = useOutletContext<LayoutContext>()
  const {
    isDark,
    availableModels,
    models,
    displayName,
    backgroundEffect,
    defaultModel,
  } = useAppContext()

  const {
    conversations,
    projects,
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
    refreshTraceObservations,
  } = store

  // Rate-limit cooldowns are per-conversation (epoch-ms when the lock lifts)
  const [rateLimitUntil, setRateLimitUntil] = useState<Record<string, number>>({})
  const [now, setNow] = useState(() => Date.now())

  // Composer's mode picker (Fast / Pro / Create Image) -- a routing hint
  // sent with every /chat call, not a per-conversation persisted setting.
  const [mode, setMode] = useState<Mode>('fast')

  // Document upload states
  const [attachedDoc, setAttachedDoc] = useState<{ id: string; name: string } | null>(null)
  const [isUploading, setIsUploading] = useState(false)

  // F-11: attached image state (vision Q&A) -- kept client-side only until
  // Send, never uploaded/persisted like a doc (no backend storage at all;
  // read straight into a data URI and sent along with the next /chat call).
  const [attachedImage, setAttachedImage] = useState<{ name: string; previewUrl: string; b64: string; mime: string } | null>(null)

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

  // P.4 — ProjectPage's landing composer creates this draft chat and hands
  // off a pending message/upload via router state instead of duplicating
  // ChatPage's own streaming logic. Fire it once on arrival, then clear the
  // state so a refresh/back-navigation never resends it. `pendingHandledRef`
  // is a synchronous, same-mount-persistent guard against React 18
  // StrictMode's intentional dev-only double-invocation of effects (mount →
  // effect → cleanup → effect again) -- without it, this real side effect
  // (sending a message / promoting the draft) fires twice, double-sends,
  // and the second, corrupted call can race with the first's project-scope
  // promotion.
  const pendingHandledRef = useRef(false)
  useEffect(() => {
    if (pendingHandledRef.current) return
    const pendingMessage = (location.state as { pendingMessage?: string } | null)?.pendingMessage
    const pendingUploadFile = (location.state as { pendingUploadFile?: File } | null)?.pendingUploadFile
    if (!pendingMessage && !pendingUploadFile) return
    pendingHandledRef.current = true
    navigate(location.pathname, { replace: true, state: {} })
    if (pendingUploadFile) {
      handleUpload(pendingUploadFile).then(() => {
        if (pendingMessage) handleSend(pendingMessage)
      })
    } else if (pendingMessage) {
      handleSend(pendingMessage)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state])

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

  // When the active conversation changes, drop any attached document/image.
  useEffect(() => {
    if (!activeConvId) return
    setAttachedDoc(null)
    setAttachedImage((prev) => {
      if (prev) URL.revokeObjectURL(prev.previewUrl)
      return null
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeConvId])

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

    // F-11: an attached image is one-turn-only -- captured and cleared here
    // (not on conv switch like the doc attachment, which lingers all
    // conversation since doc_id is otherwise inert) so it's never silently
    // resent with a later, unrelated message.
    const imageToSend = attachedImage
    if (imageToSend) {
      URL.revokeObjectURL(imageToSend.previewUrl)
      setAttachedImage(null)
    }

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
    // F-11 follow-up: any tool call this turn means the persisted message
    // will carry `observation` fields the live trace never does -- flagged
    // here so onDone can backfill them via refreshTraceObservations once
    // the turn (and its server-side persist) is actually done.
    let usedToolThisTurn = false

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
              m.id === assistantId
                ? { ...m, content: m.content + delta, segments: appendTextSegment(m.segments, delta) }
                : m,
            ),
          )
        },
        onDone: (viaProvider) => {
          setMessagesFor(convId, (prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                  ...m,
                  viaProvider,
                  trace: settleRunningTrace(m.trace || []),
                  segments: settleRunningSegment(m.segments || []),
                }
                : m,
            ),
          )
          setStreaming(convId, false)
          streamsRef.current.delete(convId)
          bumpAfterTurn(convId)
          quietTitleRefresh()
          if (usedToolThisTurn) void refreshTraceObservations(convId)
        },
        onError: (err) => {
          setMessagesFor(convId, (prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? {
                  ...m,
                  content: `Error: ${err}`,
                  trace: settleRunningTrace(m.trace || []),
                  segments: settleRunningSegment(m.segments || []),
                }
                : m,
            ),
          )
          setStreaming(convId, false)
          streamsRef.current.delete(convId)
        },
        onStep: (label, detail, agent) => {
          if (TOOL_STEP_RE.test(label)) usedToolThisTurn = true
          setMessagesFor(convId, (prev) =>
            prev.map((m) => {
              if (m.id !== assistantId) return m
              const entry: TraceEntry = TOOL_STEP_RE.test(label)
                ? { kind: 'tool', agent, label, detail, status: 'running', startedAt: Date.now() }
                : { kind: 'step', agent, label, detail }
              return { ...m, trace: appendTraceEntry(m.trace, entry), segments: appendToolSegment(m.segments, entry) }
            }),
          )
        },
        onToolCall: (name, agent) => {
          // Enriches the tool entry onStep just pushed with its resolved
          // tool/subagent name (client.ts fires this right after onStep for
          // the same event) -- TraceView otherwise falls back to the raw label.
          setMessagesFor(convId, (prev) =>
            prev.map((m) => {
              if (m.id !== assistantId) return m
              let next = m
              if (m.trace && m.trace.length > 0) {
                const last = m.trace[m.trace.length - 1]
                if (last.kind === 'tool' && last.status === 'running' && last.agent === agent) {
                  next = { ...next, trace: [...m.trace.slice(0, -1), { ...last, name }] }
                }
              }
              if (m.segments && m.segments.length > 0) {
                const last = m.segments[m.segments.length - 1]
                if (last.type === 'tool' && last.entry.kind === 'tool' && last.entry.status === 'running' && last.entry.agent === agent) {
                  next = { ...next, segments: [...m.segments.slice(0, -1), { type: 'tool', entry: { ...last.entry, name } }] }
                }
              }
              return next
            }),
          )
        },
        onToolResult: (name, observation, agent) => {
          // F-11 follow-up: attaches the tool's real result (e.g.
          // generate_image's job id) to its trace/segment entry the moment
          // it's actually available -- previously `observation` never
          // arrived until a later reload, so anything keyed off it (the
          // image chip) could never show up live. Matches the most recent
          // still-running entry for this exact tool+agent, same pairing
          // onToolCall already relies on.
          setMessagesFor(convId, (prev) =>
            prev.map((m) => {
              if (m.id !== assistantId) return m
              let next = m
              if (m.trace) {
                const idx = [...m.trace].reverse().findIndex(
                  (e) => e.kind === 'tool' && e.name === name && e.agent === agent && e.status === 'running',
                )
                if (idx !== -1) {
                  const i = m.trace.length - 1 - idx
                  const updated = [...m.trace]
                  updated[i] = { ...updated[i], observation }
                  next = { ...next, trace: updated }
                }
              }
              if (m.segments) {
                const idx = [...m.segments].reverse().findIndex(
                  (s) => s.type === 'tool' && s.entry.kind === 'tool' && s.entry.name === name && s.entry.agent === agent && s.entry.status === 'running',
                )
                if (idx !== -1) {
                  const i = m.segments.length - 1 - idx
                  const seg = m.segments[i]
                  if (seg.type === 'tool') {
                    const updated = [...m.segments]
                    updated[i] = { ...seg, entry: { ...seg.entry, observation } }
                    next = { ...next, segments: updated }
                  }
                }
              }
              return next
            }),
          )
        },
        onMemoryHit: (summary, scope, sourceConvId) => {
          setMessagesFor(convId, (prev) =>
            prev.map((m) => {
              if (m.id !== assistantId) return m
              const entry: TraceEntry = {
                kind: 'memory_hit',
                agent: 'main',
                summary,
                scope: scope === 'project' ? 'project' : scope === 'chat' ? 'chat' : undefined,
                sourceConvId,
              }
              return { ...m, trace: appendTraceEntry(m.trace, entry), segments: appendToolSegment(m.segments, entry) }
            }),
          )
        },
        onModelCall: (model, purpose) => {
          setMessagesFor(convId, (prev) =>
            prev.map((m) => {
              if (m.id !== assistantId) return m
              const entry: TraceEntry = { kind: 'model_call', agent: 'main', model, purpose }
              return { ...m, trace: appendTraceEntry(m.trace, entry), segments: appendToolSegment(m.segments, entry) }
            }),
          )
        },
        onCitation: (url, title) => {
          setMessagesFor(convId, (prev) =>
            prev.map((m) => {
              if (m.id !== assistantId) return m
              const existing = m.citations || []
              if (existing.some((c) => c.url === url)) return m // de-dup by URL
              const entry: TraceEntry = { kind: 'citation', agent: 'main', url, title }
              return {
                ...m,
                citations: [...existing, { url, title }],
                trace: appendTraceEntry(m.trace, entry),
                segments: appendToolSegment(m.segments, entry),
              }
            }),
          )
        },
        onProviderSwitch: (from, to) => {
          // Renders solely inside the assistant bubble's trace (TraceView's
          // provider_switch StepRow) — no standalone notice message. A
          // separate role:'notice' pill used to be spliced in here too
          // (pre-Phase-A / Step R4 era), which duplicated this same event as
          // a floating bubble ABOVE the reply, breaking the "one continuous
          // flow" the agent trace (A.8) was built to guarantee. Removed
          // 2026-07-14.
          setMessagesFor(convId, (prev) =>
            prev.map((m) => {
              if (m.id !== assistantId) return m
              const entry: TraceEntry = { kind: 'provider_switch', agent: 'main', from, to }
              return { ...m, trace: appendTraceEntry(m.trace, entry), segments: appendToolSegment(m.segments, entry) }
            }),
          )
        },
      },
      defaultModel,
      attachedDoc?.id || undefined,
      convId,
      controller.signal,
      imageToSend ? { b64: imageToSend.b64, mime: imageToSend.mime } : undefined,
      mode,
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

  function handleUploadImage(file: File) {
    // F-11: no backend call at all -- unlike handleUpload's doc pipeline,
    // an attached image is never indexed/persisted, just read straight into
    // a data URI and held until Send (or dropped on remove/conv switch).
    const previewUrl = URL.createObjectURL(file)
    const reader = new FileReader()
    reader.onload = () => {
      const dataUrl = reader.result as string
      const b64 = dataUrl.slice(dataUrl.indexOf(',') + 1)
      setAttachedImage({ name: file.name, previewUrl, b64, mime: file.type || 'image/png' })
    }
    reader.onerror = () => {
      URL.revokeObjectURL(previewUrl)
      alert('Failed to read the image file.')
    }
    reader.readAsDataURL(file)
  }

  function handleRemoveImageAttachment() {
    setAttachedImage((prev) => {
      if (prev) URL.revokeObjectURL(prev.previewUrl)
      return null
    })
  }

  const activeConv = conversations.find((c) => c.id === activeConvId)
  const activeConvProject = activeConv?.project_id
    ? projects.find((p) => p.id === activeConv.project_id)
    : undefined
  const headerTitle = activeConv ? activeConv.title : 'PAWN Chat'
  const headerTitleForAttr = activeConvProject ? `${activeConvProject.name} / ${headerTitle}` : headerTitle

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
        <div className="flex items-center gap-2 h-7 pl-2 pr-3 bg-theme-surface border border-theme-border/60 rounded-xl shadow-md pointer-events-auto z-20 transition-all">
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
          <h1
            className="flex items-center gap-1.5 text-xs font-semibold text-theme-text truncate max-w-[150px] md:max-w-xs select-none"
            title={headerTitleForAttr}
          >
            {activeConvProject && (
              <>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    navigate(`/project/${activeConvProject.id}`)
                  }}
                  className="text-theme-text-muted hover:text-theme-text hover:underline truncate transition-colors cursor-pointer"
                >
                  {activeConvProject.name}
                </button>
                <span className="text-theme-text-muted/50 select-none shrink-0">/</span>
              </>
            )}
            <span className="truncate">{headerTitle}</span>
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
              {rateLimitCountdown !== null && (
                <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 text-amber-700 dark:text-amber-300 text-xs font-medium animate-in fade-in">
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4 shrink-0">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm.75-13a.75.75 0 00-1.5 0v5c0 .414.336.75.75.75h4a.75.75 0 000-1.5h-3.25V5z" clipRule="evenodd" />
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
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm.75-13a.75.75 0 00-1.5 0v5c0 .414.336.75.75.75h4a.75.75 0 000-1.5h-3.25V5z" clipRule="evenodd" />
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
                onUploadImage={handleUploadImage}
                attachment={attachedDoc}
                onRemoveAttachment={() => setAttachedDoc(null)}
                imageAttachment={attachedImage}
                onRemoveImageAttachment={handleRemoveImageAttachment}
                mode={mode}
                onChangeMode={setMode}
              />
            </div>
          </div>
        </div>
      )}

      {/* Floating Bottom Input Area — only when chat has messages */}
      {messages.length > 0 && (
      <div className="absolute bottom-0 left-0 right-0 z-20 pointer-events-none flex flex-col items-center bg-gradient-to-t from-theme-bg via-theme-bg/85 to-transparent">
        <div className="w-full max-w-3xl flex flex-col gap-2 pointer-events-auto pb-4 px-4">
          {rateLimitCountdown !== null && (
            <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 text-amber-700 dark:text-amber-300 text-xs font-medium animate-in fade-in">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4 shrink-0">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm.75-13a.75.75 0 00-1.5 0v5c0 .414.336.75.75.75h4a.75.75 0 000-1.5h-3.25V5z" clipRule="evenodd" />
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
            onUploadImage={handleUploadImage}
            attachment={attachedDoc}
            onRemoveAttachment={() => setAttachedDoc(null)}
            imageAttachment={attachedImage}
            onRemoveImageAttachment={handleRemoveImageAttachment}
            mode={mode}
            onChangeMode={setMode}
          />
        </div>
      </div>
      )}
    </div>
  )
}
