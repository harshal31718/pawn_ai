/** localStorage-backed cache of the conversation list + messages-by-conversation,
 *  scoped per user. The client is the source of truth for the UI; this cache makes
 *  switching and reload instant. Persistence is debounced and bounded (LRU + byte
 *  ceiling) to stay under the ~5 MB localStorage quota.
 */

import type { CachedConversation, CachedProject, PersistedMsg } from '../types'
import type { ConversationMeta, Project } from '../api/client'

const CACHE_VERSION = 1
const MAX_MSG_CONVS = 30          // keep message arrays for the N most-recent convs
const MAX_BYTES = 4_000_000       // ~4 MB serialized ceiling (quota is ~5 MB)
const SAVE_DEBOUNCE_MS = 300

export interface CacheShape {
  version: number
  conversations: CachedConversation[]
  projects: CachedProject[]
  messages: Record<string, PersistedMsg[]>
  lru: string[]                   // convIds, most-recently-touched first
}

function keyFor(userId: string | null): string {
  return `pawn-cache:v${CACHE_VERSION}:${userId ?? 'anon'}`
}

function emptyCache(): CacheShape {
  return { version: CACHE_VERSION, conversations: [], projects: [], messages: {}, lru: [] }
}

/** Synchronous, corruption-safe load. Any parse error or version mismatch yields a
 *  fresh empty cache — never throws into render. (Future migrations hook in here.) */
export function loadCache(userId: string | null): CacheShape {
  try {
    const raw = localStorage.getItem(keyFor(userId))
    if (!raw) return emptyCache()
    const parsed = JSON.parse(raw)
    if (
      !parsed ||
      parsed.version !== CACHE_VERSION ||
      !Array.isArray(parsed.conversations) ||
      typeof parsed.messages !== 'object' ||
      parsed.messages === null
    ) {
      return emptyCache()
    }
    return {
      version: CACHE_VERSION,
      conversations: parsed.conversations as CachedConversation[],
      // `projects` is new (Phase M) — a pre-existing cache written before this
      // field existed simply has none yet, not a corrupt cache.
      projects: Array.isArray(parsed.projects) ? (parsed.projects as CachedProject[]) : [],
      messages: parsed.messages as Record<string, PersistedMsg[]>,
      lru: Array.isArray(parsed.lru) ? (parsed.lru as string[]) : [],
    }
  } catch {
    return emptyCache()
  }
}

/** Drop message arrays beyond the MAX_MSG_CONVS most-recent convs, then trim by the
 *  byte ceiling. Meta for all convs is always retained. Persistence-only — the
 *  in-memory store keeps full messages for the session. */
function evictForPersist(
  conversations: CachedConversation[],
  messages: Record<string, PersistedMsg[]>,
  lru: string[],
): { messages: Record<string, PersistedMsg[]>; lru: string[] } {
  const keep = new Set(lru.slice(0, MAX_MSG_CONVS))
  const out: Record<string, PersistedMsg[]> = {}
  for (const [cid, msgs] of Object.entries(messages)) {
    if (keep.has(cid)) out[cid] = msgs
  }
  // recent-first order of surviving convs; pop least-recent until under the ceiling
  const order = lru.filter((id) => out[id])
  while (order.length > 1 && JSON.stringify({ conversations, messages: out }).length > MAX_BYTES) {
    const drop = order.pop()
    if (drop) delete out[drop]
  }
  const nextLru = lru.filter((id) => out[id] || !messages[id])
  return { messages: out, lru: nextLru }
}

// ── Debounced writer ─────────────────────────────────────────────────────────

let timer: ReturnType<typeof setTimeout> | undefined
let pending: { userId: string | null; cache: CacheShape } | null = null

export function scheduleSave(userId: string | null, cache: CacheShape): void {
  pending = { userId, cache }
  if (timer) clearTimeout(timer)
  timer = setTimeout(flushPending, SAVE_DEBOUNCE_MS)
}

/** Write any pending cache immediately (also called on pagehide/tab-hide). */
export function flushPending(): void {
  if (!pending) return
  const { userId, cache } = pending
  pending = null
  if (timer) {
    clearTimeout(timer)
    timer = undefined
  }
  try {
    const { messages, lru } = evictForPersist(cache.conversations, cache.messages, cache.lru)
    const data: CacheShape = {
      version: CACHE_VERSION,
      conversations: cache.conversations,
      projects: cache.projects,
      messages,
      lru,
    }
    localStorage.setItem(keyFor(userId), JSON.stringify(data))
  } catch {
    // Quota exceeded or serialization failure — best-effort cache, drop silently.
  }
}

if (typeof window !== 'undefined') {
  window.addEventListener('pagehide', flushPending)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flushPending()
  })
}

// ── Reconciliation ───────────────────────────────────────────────────────────

/** Merge server conversation metadata into the local list. Pure: returns a new
 *  array, never touches active selection or messages.
 *  - Adopt the server title only if the conv is still 'New Chat' or the server was
 *    updated more recently than the local change (picks up server auto-titles
 *    without stomping a user rename).
 *  - Keep a local conv absent from the server if it's unsynced (optimistic, not yet
 *    drained); drop it if it was synced (deleted elsewhere).
 *  - Add server convs not present locally. */
export function mergeServerMeta(
  local: CachedConversation[],
  server: ConversationMeta[],
): CachedConversation[] {
  const serverById = new Map(server.map((s) => [s.id, s]))
  const localIds = new Set(local.map((l) => l.id))
  const result: CachedConversation[] = []

  for (const l of local) {
    const s = serverById.get(l.id)
    if (!s) {
      if (!l._synced) result.push(l)
      continue
    }
    const serverUpdated = Date.parse(s.updated_at) || 0
    const adoptTitle = l.title === 'New Chat' || serverUpdated > l._localUpdatedAt
    result.push({
      ...l,
      title: adoptTitle ? s.title : l.title,
      message_count: s.message_count,
      updated_at: s.updated_at,
      model_id: s.model_id || l.model_id,
      project_id: s.project_id ?? l.project_id,
      _synced: true,
    })
  }

  for (const s of server) {
    if (!localIds.has(s.id)) {
      result.push({ ...s, _synced: true, _localUpdatedAt: 0 })
    }
  }

  result.sort((a, b) => (Date.parse(b.updated_at) || 0) - (Date.parse(a.updated_at) || 0))
  return result
}

/** Merge server project metadata into the local list — same reconciliation
 *  shape as `mergeServerMeta` (adopt server name unless locally renamed more
 *  recently; keep unsynced local-only projects; drop synced ones the server
 *  no longer has; add new server projects). */
export function mergeServerProjects(
  local: CachedProject[],
  server: Project[],
): CachedProject[] {
  const serverById = new Map(server.map((s) => [s.id, s]))
  const localIds = new Set(local.map((l) => l.id))
  const result: CachedProject[] = []

  for (const l of local) {
    const s = serverById.get(l.id)
    if (!s) {
      if (!l._synced) result.push(l)
      continue
    }
    const serverUpdated = Date.parse(s.updated_at ?? '') || 0
    const adoptName = l.name === 'New Project' || serverUpdated > l._localUpdatedAt
    result.push({
      ...l,
      name: adoptName ? s.name : l.name,
      chat_count: s.chat_count,
      updated_at: s.updated_at ?? l.updated_at,
      _synced: true,
    })
  }

  for (const s of server) {
    if (!localIds.has(s.id)) {
      result.push({ ...s, _synced: true, _localUpdatedAt: 0 })
    }
  }

  result.sort((a, b) => (Date.parse(b.updated_at ?? '') || 0) - (Date.parse(a.updated_at ?? '') || 0))
  return result
}
