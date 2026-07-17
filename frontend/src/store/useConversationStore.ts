/** The single owner of conversation list + messages + active selection, backed by
 *  the localStorage cache and the background sync queue. Everything updates
 *  optimistically (instant UI); Drive persistence happens in the background.
 *
 *  Messages are keyed by conversation, so a stream writing to its captured
 *  conversation id keeps landing in the right place even if the user switches away.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import {
  createConversation as createConversationApi,
  fetchConversation,
  fetchConversations,
  getProjects,
  moveChatToProject as moveChatToProjectApi,
} from '../api/client'
import type { CachedConversation, CachedProject, Message, PersistedMsg } from '../types'
import {
  flushPending,
  loadCache,
  mergeServerMeta,
  mergeServerProjects,
  scheduleSave,
} from './conversationCache'
import { mid, newConvId } from './ids'
import { SyncQueue } from './syncQueue'

const TITLE_REFRESH_DEBOUNCE_MS = 1500

function toPersisted(msgs: Message[]): PersistedMsg[] {
  return msgs.map((m) => ({
    id: m.id,
    role: m.role,
    content: m.content,
    ...(m.viaProvider ? { viaProvider: m.viaProvider } : {}),
    // Phase A / A.8: traces/citations now survive the cache round-trip too
    // (previously dropped here — a reload before the server refetch landed
    // would show a bare reply with no trace).
    ...(m.trace && m.trace.length > 0 ? { trace: m.trace } : {}),
    ...(m.citations && m.citations.length > 0 ? { citations: m.citations } : {}),
    // Phase N: segments carry the live interleaved arrival order through a
    // same-session reload too (before the next server round-trip refetches
    // the non-interleaved persisted shape via backgroundLoadDetail below).
    ...(m.segments && m.segments.length > 0 ? { segments: m.segments } : {}),
  }))
}

function fromPersisted(msgs: PersistedMsg[]): Message[] {
  return msgs.map((m) => ({
    id: m.id,
    role: m.role,
    content: m.content,
    viaProvider: m.viaProvider,
    trace: m.trace,
    citations: m.citations,
    segments: m.segments,
  }))
}

function countTurns(msgs: Message[] | undefined): number {
  if (!msgs) return 0
  return msgs.filter((m) => m.role === 'user' || m.role === 'assistant').length
}

export interface ConversationStore {
  conversations: CachedConversation[]
  projects: CachedProject[]
  activeConvId: string | null
  messages: Message[] // active conversation's messages
  pendingIds: Set<string>
  syncError: string | null
  draftConvId: string | null
  draftProjectId: string | null
  streamingConvIds: Set<string>
  selectConversation: (id: string) => void
  createConversation: (targetProjectId?: string) => string
  createProjectChat: (projectId: string) => Promise<string>
  promoteDraft: (id: string) => void
  deleteConversation: (id: string) => void
  renameConversation: (id: string, title: string) => void
  setMessagesFor: (convId: string, updater: (prev: Message[]) => Message[]) => void
  bumpAfterTurn: (convId: string) => void
  setStreaming: (convId: string, on: boolean) => void
  quietTitleRefresh: () => void
  refreshTraceObservations: (id: string) => Promise<void>
  createProject: (name?: string) => string
  renameProject: (id: string, name: string) => void
  updateProjectDescription: (id: string, description: string) => void
  deleteProject: (id: string) => void
  moveChatToProject: (convId: string, projectId: string) => void
  removeChatFromProject: (convId: string) => void
}

export function useConversationStore(
  userId: string | null,
  defaultModel: string,
): ConversationStore {
  // Hydrate the cache exactly once (not on every render) so the first paint shows
  // last state with zero latency.
  const hydrated = useRef<{
    conversations: CachedConversation[]
    projects: CachedProject[]
    messages: Record<string, Message[]>
    lru: string[]
  } | null>(null)
  if (hydrated.current === null) {
    const cached = loadCache(userId)
    const messages: Record<string, Message[]> = {}
    for (const [cid, msgs] of Object.entries(cached.messages)) messages[cid] = fromPersisted(msgs)
    hydrated.current = { conversations: cached.conversations, projects: cached.projects, messages, lru: cached.lru }
  }

  const [conversations, setConversations] = useState<CachedConversation[]>(hydrated.current.conversations)
  const [projects, setProjects] = useState<CachedProject[]>(hydrated.current.projects)
  const [messagesByConv, setMessagesByConv] = useState<Record<string, Message[]>>(hydrated.current.messages)
  const [activeConvId, setActiveConvId] = useState<string | null>(null)
  // The unsaved "New Chat" draft: lives only in the frontend (welcome page + an
  // empty in-memory message buffer). It is NOT in `conversations`, not on Drive,
  // and not enqueued — it materializes only when the first message is sent.
  const [draftConvId, setDraftConvId] = useState<string | null>(null)
  // The unsaved "New Project" draft — same contract as draftConvId: frontend-only,
  // not in `projects`' persisted cache entry, not enqueued, until promoted by the
  // first meaningful edit (rename, description, or starting a chat inside it).
  const [draftProjectId, setDraftProjectId] = useState<string | null>(null)
  const [pendingIds, setPendingIds] = useState<Set<string>>(new Set())
  const [syncError, setSyncError] = useState<string | null>(null)
  // Which conversations are currently generating. Per-conversation so multiple
  // chats can stream concurrently; the composer only locks the active one.
  const [streamingConvIds, setStreamingConvIds] = useState<Set<string>>(new Set())

  // Refs mirror state for stale-free reads inside callbacks.
  const conversationsRef = useRef(conversations)
  const projectsRef = useRef(projects)
  const messagesByConvRef = useRef(messagesByConv)
  const activeConvIdRef = useRef(activeConvId)
  const draftConvIdRef = useRef(draftConvId)
  const draftProjectIdRef = useRef(draftProjectId)
  // Target project (if any) a draft should land in once promoted on first send
  // (the "new chat in project" flow) — a plain ref since it's write-once,
  // read-once per draft and never drives a render itself.
  const draftTargetProjectIdRef = useRef<string | null>(null)
  const defaultModelRef = useRef(defaultModel)
  const lruRef = useRef<string[]>(hydrated.current.lru)
  const streamingConvIdsRef = useRef<Set<string>>(streamingConvIds)
  const fetchSeqRef = useRef(0)
  const syncRef = useRef<SyncQueue | null>(null)
  const titleTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => { conversationsRef.current = conversations }, [conversations])
  useEffect(() => { projectsRef.current = projects }, [projects])
  useEffect(() => { messagesByConvRef.current = messagesByConv }, [messagesByConv])
  useEffect(() => { activeConvIdRef.current = activeConvId }, [activeConvId])
  useEffect(() => { draftConvIdRef.current = draftConvId }, [draftConvId])
  useEffect(() => { draftProjectIdRef.current = draftProjectId }, [draftProjectId])
  useEffect(() => { defaultModelRef.current = defaultModel }, [defaultModel])

  const touchLru = useCallback((id: string) => {
    lruRef.current = [id, ...lruRef.current.filter((x) => x !== id)]
  }, [])
  const removeLru = useCallback((id: string) => {
    lruRef.current = lruRef.current.filter((x) => x !== id)
  }, [])

  // Materialize a draft project: clears the draft slot (so "New project" opens a
  // fresh one next time) and enqueues the real create op with whatever name it has
  // at the moment of promotion — mirrors promoteDraft's chat-draft contract below.
  const promoteProjectDraft = useCallback((id: string, name: string) => {
    if (draftProjectIdRef.current !== id) return
    draftProjectIdRef.current = null
    setDraftProjectId(null)
    syncRef.current?.enqueue({ kind: 'createProject', projectId: id, name })
  }, [])

  // Persist (debounced) whenever the list or messages change. The unsaved chat/project
  // drafts are excluded — both are frontend-only until promoted.
  useEffect(() => {
    const messages: Record<string, PersistedMsg[]> = {}
    for (const [cid, msgs] of Object.entries(messagesByConv)) {
      if (cid === draftConvId) continue
      messages[cid] = toPersisted(msgs)
    }
    const persistProjects = draftProjectId ? projects.filter((p) => p.id !== draftProjectId) : projects
    scheduleSave(userId, { version: 1, conversations, projects: persistProjects, messages, lru: lruRef.current })
  }, [conversations, projects, messagesByConv, draftConvId, draftProjectId, userId])

  // ── Background reconciliation ──────────────────────────────────────────────

  const reconcile = useCallback(async () => {
    const [list, projectList] = await Promise.all([
      fetchConversations(),
      getProjects().catch(() => projectsRef.current), // Drive-unlinked users still get chats
    ])
    setConversations((prev) => mergeServerMeta(prev, list))
    setProjects((prev) => mergeServerProjects(prev, projectList))
  }, [])

  const quietTitleRefresh = useCallback(() => {
    if (titleTimerRef.current) clearTimeout(titleTimerRef.current)
    titleTimerRef.current = setTimeout(() => {
      reconcile().catch(() => {})
    }, TITLE_REFRESH_DEBOUNCE_MS)
  }, [reconcile])

  const backgroundLoadDetail = useCallback(async (id: string, seq: number) => {
    try {
      const detail = await fetchConversation(id)
      if (seq !== fetchSeqRef.current) return // user switched away — ignore stale result
      const msgs = detail.messages
        .filter((m) => m.role === 'user' || m.role === 'assistant')
        .map((m) => ({
          id: mid(),
          role: m.role as 'user' | 'assistant',
          content: m.content,
          trace: m.trace,
          citations: m.citations,
        }))
      setMessagesByConv((prev) => ({ ...prev, [id]: msgs }))
      setConversations((prev) => mergeServerMeta(prev, [detail.meta]))
    } catch {
      // leave cache as-is; user can retry by reopening
    }
  }, [])

  // F-11 follow-up (frontend cache-precedence bug, live-found): a live SSE
  // trace's `tool` entries never carry `observation` (only ever attached
  // server-side on the persisted message) -- for a chat created+completed
  // within the current session, `selectConversation` trusts the cache and
  // never re-fetches, so a tool-call preview (e.g. ImageJobChip's job id)
  // stays permanently stuck showing just the raw args, even across a hard
  // reload. Unlike backgroundLoadDetail (used when nothing is cached at all
  // and safe to fully replace), this merges in *only* the missing
  // `observation` strings by matching each message's cached trace entries
  // (and, for a still-live-cached message, its equivalent `segments` tool
  // entries -- Phase N's interleaved render path reads from segments, not
  // trace, so both must be patched for the image chip to actually appear)
  // against the freshly-fetched ones by array position -- content and
  // everything else stay exactly as they are, so there's no risk of a
  // slower/eventually-consistent Drive read clobbering on-screen state.
  const refreshTraceObservations = useCallback(async (id: string) => {
    try {
      const detail = await fetchConversation(id)
      const byId = new Map(detail.messages.filter((m) => m.role === 'assistant').map((m, i) => [i, m]))
      let assistantIndex = 0
      setMessagesByConv((prev) => {
        const cached = prev[id]
        if (!cached) return prev
        const next = cached.map((m) => {
          if (m.role !== 'assistant') return m
          const fresh = byId.get(assistantIndex++)
          if (!fresh?.trace) return m
          const mergedTrace = m.trace?.map((entry, i) => {
            const freshEntry = fresh.trace?.[i]
            return entry.kind === 'tool' && !entry.observation && freshEntry?.observation
              ? { ...entry, observation: freshEntry.observation }
              : entry
          })
          let toolSegIdx = 0
          const mergedSegments = m.segments?.map((seg) => {
            if (seg.type !== 'tool') return seg
            const i = toolSegIdx++
            const freshEntry = fresh.trace?.[i]
            return seg.entry.kind === 'tool' && !seg.entry.observation && freshEntry?.observation
              ? { ...seg, entry: { ...seg.entry, observation: freshEntry.observation } }
              : seg
          })
          return { ...m, ...(mergedTrace ? { trace: mergedTrace } : {}), ...(mergedSegments ? { segments: mergedSegments } : {}) }
        })
        return { ...prev, [id]: next }
      })
    } catch {
      // best-effort backfill; leave cache as-is on failure
    }
  }, [])

  // ── Optimistic mutators ─────────────────────────────────────────────────────

  const selectConversation = useCallback(
    (id: string) => {
      setActiveConvId(id)
      touchLru(id)
      const seq = ++fetchSeqRef.current
      // Only fetch messages when we have NONE cached for this conv (e.g. created on
      // another device). A known conv (even empty []) is trusted from cache so a
      // slow/eventually-consistent Drive read can never clobber on-screen messages.
      const haveCached = messagesByConvRef.current[id] !== undefined
      if (!haveCached && !streamingConvIdsRef.current.has(id)) {
        void backgroundLoadDetail(id, seq)
      }
    },
    [touchLru, backgroundLoadDetail],
  )

  // New Chat: open a frontend-only DRAFT. Nothing is created on Drive/Postgres/local
  // and no op is enqueued — the conversation materializes only when the first message
  // is sent (promoteDraft + the chat route's lazy-create). At most one draft exists,
  // so repeat clicks just re-focus it: no duplicates, no empty-chat files.
  //
  // `targetProjectId`, when given, is the "new chat inside this project" flow: the
  // draft is born targeting that project, and promoteDraft below both sets its
  // local project_id immediately (so it renders under the right sidebar section
  // right away) and enqueues a moveChat op so the backend places it there too —
  // there's no dedicated "create inside project" endpoint (M.5 only has move
  // in/out on an existing chat), so this is a create followed by an immediate move.
  const createConversation = useCallback((targetProjectId?: string): string => {
    const existingDraft = draftConvIdRef.current
    if (existingDraft) {
      setActiveConvId(existingDraft)
      return existingDraft
    }
    // Starting a chat inside a still-draft project is a meaningful action —
    // promote the project now so the moveChat op (enqueued when this chat's own
    // draft promotes on first send) has a real project to land in.
    if (targetProjectId && targetProjectId === draftProjectIdRef.current) {
      const draftProject = projectsRef.current.find((p) => p.id === targetProjectId)
      promoteProjectDraft(targetProjectId, draftProject?.name ?? 'New Project')
    }
    const id = newConvId()
    draftTargetProjectIdRef.current = targetProjectId ?? null
    setDraftConvId(id)
    setMessagesByConv((prev) => ({ ...prev, [id]: [] }))
    setActiveConvId(id)
    return id
  }, [promoteProjectDraft])

  // Convert the draft into a real conversation at first send: add its meta to the
  // list (sidebar row appears) and clear the draft. No create op — the chat route
  // lazy-creates it on Drive with this id.
  const promoteDraft = useCallback((id: string) => {
    if (draftConvIdRef.current !== id) return
    const targetProjectId = draftTargetProjectIdRef.current
    draftTargetProjectIdRef.current = null
    const now = new Date().toISOString()
    const meta: CachedConversation = {
      id,
      title: 'New Chat',
      created_at: now,
      updated_at: now,
      model_id: defaultModelRef.current,
      message_count: 0,
      project_id: targetProjectId ?? undefined,
      _synced: false,
      _localUpdatedAt: Date.now(),
    }
    setConversations((prev) => [meta, ...prev])
    setDraftConvId(null)
    touchLru(id)
    if (targetProjectId) {
      syncRef.current?.enqueue({ kind: 'moveChat', convId: id, projectId: targetProjectId })
    }
  }, [touchLru])

  // Starting a chat from a project's own landing composer (ProjectPage), as
  // opposed to a standalone "New chat": the project id must be assigned
  // BEFORE the chat window opens, not raced in the background. The
  // create-then-immediate-move pattern above (promoteDraft) enqueues its
  // moveChat op fire-and-forget at promote time, which can beat the chat's
  // own lazy server-side creation and 404 on the first try (found live,
  // 2026-07-16 — a chat created this way stayed in the standalone `chats/`
  // Drive folder, invisible to project-scoped memory, until the sync
  // queue's retries happened to land afterwards). This does the same two
  // server calls directly, awaited in order, so the conversation is
  // guaranteed to exist before the move is attempted — no race, no need to
  // rely on retry-based eventual consistency.
  const createProjectChat = useCallback(async (projectId: string): Promise<string> => {
    const id = newConvId()
    await createConversationApi(undefined, defaultModelRef.current, id)
    await moveChatToProjectApi(projectId, id)
    const now = new Date().toISOString()
    const meta: CachedConversation = {
      id,
      title: 'New Chat',
      created_at: now,
      updated_at: now,
      model_id: defaultModelRef.current,
      message_count: 0,
      project_id: projectId,
      _synced: true,
      _localUpdatedAt: Date.now(),
    }
    setConversations((prev) => [meta, ...prev])
    setMessagesByConv((prev) => ({ ...prev, [id]: [] }))
    // Make it the active conversation synchronously, exactly as the draft-based
    // createConversation does — otherwise ChatPage mounts on the new URL with a
    // stale activeConvId and its own handleSend (`activeConvId ?? createConversation()`)
    // spawns a SECOND, orphaned draft instead of sending into this pre-scoped chat.
    setActiveConvId(id)
    touchLru(id)
    return id
  }, [touchLru])

  const deleteConversation = useCallback(
    (id: string) => {
      const remaining = conversationsRef.current.filter((c) => c.id !== id)
      setConversations(remaining)
      setMessagesByConv((prev) => {
        const next = { ...prev }
        delete next[id]
        return next
      })
      removeLru(id)
      if (activeConvIdRef.current === id) {
        if (remaining.length > 0) selectConversation(remaining[0].id)
        else createConversation()
      }
      syncRef.current?.enqueue({ kind: 'delete', convId: id })
    },
    [removeLru, selectConversation, createConversation],
  )

  const renameConversation = useCallback((id: string, title: string) => {
    setConversations((prev) =>
      prev.map((c) => (c.id === id ? { ...c, title, _localUpdatedAt: Date.now() } : c)),
    )
    syncRef.current?.enqueue({ kind: 'rename', convId: id, title })
  }, [])

  const setMessagesFor = useCallback(
    (convId: string, updater: (prev: Message[]) => Message[]) => {
      setMessagesByConv((prev) => ({ ...prev, [convId]: updater(prev[convId] ?? []) }))
      touchLru(convId)
    },
    [touchLru],
  )

  const bumpAfterTurn = useCallback((convId: string) => {
    setConversations((prev) => {
      const now = new Date().toISOString()
      const updated = prev.map((c) =>
        c.id === convId
          ? {
              ...c,
              message_count: countTurns(messagesByConvRef.current[convId]),
              updated_at: now,
              _synced: true,
              _localUpdatedAt: Date.now(),
            }
          : c,
      )
      updated.sort((a, b) => (Date.parse(b.updated_at) || 0) - (Date.parse(a.updated_at) || 0))
      return updated
    })
  }, [])

  const setStreaming = useCallback((convId: string, on: boolean) => {
    setStreamingConvIds((prev) => {
      const next = new Set(prev)
      if (on) next.add(convId)
      else next.delete(convId)
      streamingConvIdsRef.current = next
      return next
    })
  }, [])

  // ── Project mutators (Phase M — memory scoping) ─────────────────────────────

  // New Project: with no name given, open a frontend-only DRAFT (same contract as
  // createConversation) — nothing is created on Drive/Postgres and no op is
  // enqueued until the draft is promoted by a rename, description edit, or a chat
  // started inside it. At most one draft exists, so repeat "New project" clicks
  // just re-focus it: no duplicate empty projects. A caller that does pass a name
  // (e.g. an inline name-first creation flow) creates for real immediately, as
  // before.
  const createProject = useCallback((name?: string): string => {
    const existingDraft = draftProjectIdRef.current
    if (existingDraft) return existingDraft
    const id = newConvId()
    const now = new Date().toISOString()
    const trimmed = name?.trim()
    const project: CachedProject = {
      id,
      name: trimmed || 'New Project',
      created_at: now,
      updated_at: now,
      chat_count: 0,
      _synced: false,
      _localUpdatedAt: Date.now(),
    }
    setProjects((prev) => [project, ...prev])
    if (trimmed) {
      syncRef.current?.enqueue({ kind: 'createProject', projectId: id, name: trimmed })
    } else {
      draftProjectIdRef.current = id
      setDraftProjectId(id)
    }
    return id
  }, [])

  const renameProject = useCallback((id: string, name: string) => {
    setProjects((prev) =>
      prev.map((p) => (p.id === id ? { ...p, name, _localUpdatedAt: Date.now() } : p)),
    )
    if (draftProjectIdRef.current === id) {
      promoteProjectDraft(id, name)
    } else {
      syncRef.current?.enqueue({ kind: 'renameProject', projectId: id, name })
    }
  }, [promoteProjectDraft])

  const updateProjectDescription = useCallback((id: string, description: string) => {
    setProjects((prev) =>
      prev.map((p) => (p.id === id ? { ...p, description, _localUpdatedAt: Date.now() } : p)),
    )
    if (draftProjectIdRef.current === id) {
      const draftProject = projectsRef.current.find((p) => p.id === id)
      promoteProjectDraft(id, draftProject?.name ?? 'New Project')
    }
    syncRef.current?.enqueue({ kind: 'updateProjectDescription', projectId: id, description })
  }, [promoteProjectDraft])

  // Cascade, mirroring the backend: removes the project and every chat inside
  // it (their memory chunks go too, server-side) — there is no undo.
  const deleteProject = useCallback(
    (id: string) => {
      const wasDraft = draftProjectIdRef.current === id
      const containedIds = new Set(
        conversationsRef.current.filter((c) => c.project_id === id).map((c) => c.id),
      )
      const remaining = conversationsRef.current.filter((c) => !containedIds.has(c.id))
      setConversations(remaining)
      setProjects((prev) => prev.filter((p) => p.id !== id))
      setMessagesByConv((prev) => {
        const next = { ...prev }
        for (const cid of containedIds) delete next[cid]
        return next
      })
      for (const cid of containedIds) removeLru(cid)
      if (activeConvIdRef.current && containedIds.has(activeConvIdRef.current)) {
        if (remaining.length > 0) selectConversation(remaining[0].id)
        else createConversation()
      }
      if (wasDraft) {
        // Never left the frontend — nothing to delete server-side.
        draftProjectIdRef.current = null
        setDraftProjectId(null)
      } else {
        syncRef.current?.enqueue({ kind: 'deleteProject', projectId: id })
      }
    },
    [removeLru, selectConversation, createConversation],
  )

  const moveChatToProject = useCallback((convId: string, projectId: string) => {
    setConversations((prev) =>
      prev.map((c) => (c.id === convId ? { ...c, project_id: projectId, _localUpdatedAt: Date.now() } : c)),
    )
    if (draftProjectIdRef.current === projectId) {
      const draftProject = projectsRef.current.find((p) => p.id === projectId)
      promoteProjectDraft(projectId, draftProject?.name ?? 'New Project')
    }
    syncRef.current?.enqueue({ kind: 'moveChat', convId, projectId })
  }, [promoteProjectDraft])

  const removeChatFromProject = useCallback((convId: string) => {
    setConversations((prev) =>
      prev.map((c) => (c.id === convId ? { ...c, project_id: undefined, _localUpdatedAt: Date.now() } : c)),
    )
    syncRef.current?.enqueue({ kind: 'moveChat', convId, projectId: null })
  }, [])

  // ── Sync queue lifecycle + mount bootstrap ──────────────────────────────────

  useEffect(() => {
    const queue = new SyncQueue(userId, {
      onSynced: (convId) =>
        setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, _synced: true } : c))),
      onProjectSynced: (projectId) =>
        setProjects((prev) => prev.map((p) => (p.id === projectId ? { ...p, _synced: true } : p))),
      notify: (ids, status) => {
        setPendingIds(ids)
        setSyncError(status)
      },
      resolveChatProject: (convId) =>
        conversationsRef.current.find((c) => c.id === convId)?.project_id ?? null,
    })
    syncRef.current = queue
    queue.start()

    // Bootstrap selection: show cached convs instantly, then reconcile with server.
    if (conversationsRef.current.length > 0) {
      setActiveConvId((prev) => prev ?? conversationsRef.current[0].id)
    }
    reconcile()
      .then(() => {
        if (conversationsRef.current.length === 0) createConversation()
        else setActiveConvId((prev) => prev ?? conversationsRef.current[0].id)
      })
      .catch(() => {
        if (conversationsRef.current.length === 0) createConversation()
      })

    return () => {
      queue.stop()
      flushPending()
      syncRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId])

  const messages = (activeConvId && messagesByConv[activeConvId]) || []

  return {
    conversations,
    projects,
    activeConvId,
    messages,
    pendingIds,
    syncError,
    draftConvId,
    draftProjectId,
    streamingConvIds,
    selectConversation,
    createConversation,
    createProjectChat,
    promoteDraft,
    deleteConversation,
    renameConversation,
    setMessagesFor,
    bumpAfterTurn,
    setStreaming,
    quietTitleRefresh,
    refreshTraceObservations,
    createProject,
    renameProject,
    updateProjectDescription,
    deleteProject,
    moveChatToProject,
    removeChatFromProject,
  }
}
