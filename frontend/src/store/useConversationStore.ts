/** The single owner of conversation list + messages + active selection, backed by
 *  the localStorage cache and the background sync queue. Everything updates
 *  optimistically (instant UI); Drive persistence happens in the background.
 *
 *  Messages are keyed by conversation, so a stream writing to its captured
 *  conversation id keeps landing in the right place even if the user switches away.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchConversation, fetchConversations } from '../api/client'
import type { CachedConversation, Message, PersistedMsg } from '../types'
import {
  flushPending,
  loadCache,
  mergeServerMeta,
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
  }))
}

function fromPersisted(msgs: PersistedMsg[]): Message[] {
  return msgs.map((m) => ({ id: m.id, role: m.role, content: m.content, viaProvider: m.viaProvider }))
}

function countTurns(msgs: Message[] | undefined): number {
  if (!msgs) return 0
  return msgs.filter((m) => m.role === 'user' || m.role === 'assistant').length
}

export interface ConversationStore {
  conversations: CachedConversation[]
  activeConvId: string | null
  messages: Message[] // active conversation's messages
  pendingIds: Set<string>
  syncError: string | null
  draftConvId: string | null
  streamingConvIds: Set<string>
  selectConversation: (id: string) => void
  createConversation: () => string
  promoteDraft: (id: string) => void
  deleteConversation: (id: string) => void
  renameConversation: (id: string, title: string) => void
  setMessagesFor: (convId: string, updater: (prev: Message[]) => Message[]) => void
  bumpAfterTurn: (convId: string) => void
  setStreaming: (convId: string, on: boolean) => void
  quietTitleRefresh: () => void
}

export function useConversationStore(
  userId: string | null,
  defaultModel: string,
): ConversationStore {
  // Hydrate the cache exactly once (not on every render) so the first paint shows
  // last state with zero latency.
  const hydrated = useRef<{
    conversations: CachedConversation[]
    messages: Record<string, Message[]>
    lru: string[]
  } | null>(null)
  if (hydrated.current === null) {
    const cached = loadCache(userId)
    const messages: Record<string, Message[]> = {}
    for (const [cid, msgs] of Object.entries(cached.messages)) messages[cid] = fromPersisted(msgs)
    hydrated.current = { conversations: cached.conversations, messages, lru: cached.lru }
  }

  const [conversations, setConversations] = useState<CachedConversation[]>(hydrated.current.conversations)
  const [messagesByConv, setMessagesByConv] = useState<Record<string, Message[]>>(hydrated.current.messages)
  const [activeConvId, setActiveConvId] = useState<string | null>(null)
  // The unsaved "New Chat" draft: lives only in the frontend (welcome page + an
  // empty in-memory message buffer). It is NOT in `conversations`, not on Drive,
  // and not enqueued — it materializes only when the first message is sent.
  const [draftConvId, setDraftConvId] = useState<string | null>(null)
  const [pendingIds, setPendingIds] = useState<Set<string>>(new Set())
  const [syncError, setSyncError] = useState<string | null>(null)
  // Which conversations are currently generating. Per-conversation so multiple
  // chats can stream concurrently; the composer only locks the active one.
  const [streamingConvIds, setStreamingConvIds] = useState<Set<string>>(new Set())

  // Refs mirror state for stale-free reads inside callbacks.
  const conversationsRef = useRef(conversations)
  const messagesByConvRef = useRef(messagesByConv)
  const activeConvIdRef = useRef(activeConvId)
  const draftConvIdRef = useRef(draftConvId)
  const defaultModelRef = useRef(defaultModel)
  const lruRef = useRef<string[]>(hydrated.current.lru)
  const streamingConvIdsRef = useRef<Set<string>>(streamingConvIds)
  const fetchSeqRef = useRef(0)
  const syncRef = useRef<SyncQueue | null>(null)
  const titleTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => { conversationsRef.current = conversations }, [conversations])
  useEffect(() => { messagesByConvRef.current = messagesByConv }, [messagesByConv])
  useEffect(() => { activeConvIdRef.current = activeConvId }, [activeConvId])
  useEffect(() => { draftConvIdRef.current = draftConvId }, [draftConvId])
  useEffect(() => { defaultModelRef.current = defaultModel }, [defaultModel])

  const touchLru = useCallback((id: string) => {
    lruRef.current = [id, ...lruRef.current.filter((x) => x !== id)]
  }, [])
  const removeLru = useCallback((id: string) => {
    lruRef.current = lruRef.current.filter((x) => x !== id)
  }, [])

  // Persist (debounced) whenever the list or messages change. The unsaved draft is
  // excluded — it's frontend-only until promoted on first message.
  useEffect(() => {
    const messages: Record<string, PersistedMsg[]> = {}
    for (const [cid, msgs] of Object.entries(messagesByConv)) {
      if (cid === draftConvId) continue
      messages[cid] = toPersisted(msgs)
    }
    scheduleSave(userId, { version: 1, conversations, messages, lru: lruRef.current })
  }, [conversations, messagesByConv, draftConvId, userId])

  // ── Background reconciliation ──────────────────────────────────────────────

  const reconcile = useCallback(async () => {
    const list = await fetchConversations()
    setConversations((prev) => mergeServerMeta(prev, list))
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
        .map((m) => ({ id: mid(), role: m.role as 'user' | 'assistant', content: m.content }))
      setMessagesByConv((prev) => ({ ...prev, [id]: msgs }))
      setConversations((prev) => mergeServerMeta(prev, [detail.meta]))
    } catch {
      // leave cache as-is; user can retry by reopening
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

  // New Chat: open a frontend-only DRAFT. Nothing is created on Drive/Supabase/local
  // and no op is enqueued — the conversation materializes only when the first message
  // is sent (promoteDraft + the chat route's lazy-create). At most one draft exists,
  // so repeat clicks just re-focus it: no duplicates, no empty-chat files.
  const createConversation = useCallback((): string => {
    const existingDraft = draftConvIdRef.current
    if (existingDraft) {
      setActiveConvId(existingDraft)
      return existingDraft
    }
    const id = newConvId()
    setDraftConvId(id)
    setMessagesByConv((prev) => ({ ...prev, [id]: [] }))
    setActiveConvId(id)
    return id
  }, [])

  // Convert the draft into a real conversation at first send: add its meta to the
  // list (sidebar row appears) and clear the draft. No create op — the chat route
  // lazy-creates it on Drive with this id.
  const promoteDraft = useCallback((id: string) => {
    if (draftConvIdRef.current !== id) return
    const now = new Date().toISOString()
    const meta: CachedConversation = {
      id,
      title: 'New Chat',
      created_at: now,
      updated_at: now,
      model_id: defaultModelRef.current,
      message_count: 0,
      _synced: false,
      _localUpdatedAt: Date.now(),
    }
    setConversations((prev) => [meta, ...prev])
    setDraftConvId(null)
    touchLru(id)
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

  // ── Sync queue lifecycle + mount bootstrap ──────────────────────────────────

  useEffect(() => {
    const queue = new SyncQueue(userId, {
      onSynced: (convId) =>
        setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, _synced: true } : c))),
      notify: (ids, status) => {
        setPendingIds(ids)
        setSyncError(status)
      },
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
    activeConvId,
    messages,
    pendingIds,
    syncError,
    draftConvId,
    streamingConvIds,
    selectConversation,
    createConversation,
    promoteDraft,
    deleteConversation,
    renameConversation,
    setMessagesFor,
    bumpAfterTurn,
    setStreaming,
    quietTitleRefresh,
  }
}
