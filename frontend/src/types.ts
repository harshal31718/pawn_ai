export interface TraceEvent {
  type: 'step' | 'memory_hit' | 'model_call' | 'provider_switch'
  label?: string
  detail?: string
  summary?: string
  model?: string
  purpose?: string
  from?: string
  to?: string
  timestamp: string
}

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'notice'
  content: string
  trace?: TraceEvent[]
  viaProvider?: string
}

export interface ChatState {
  messages: Message[]
  isStreaming: boolean
}

// ─── Client-side conversation cache + sync types ─────────────────────────────

import type { ConversationMeta } from './api/client'

/** A conversation in the client cache. `_synced` is false until the backend has
 *  acknowledged the conversation exists; `_localUpdatedAt` is a client clock used
 *  to decide whether a server title should overwrite a local (user) rename. */
export interface CachedConversation extends ConversationMeta {
  _synced: boolean
  _localUpdatedAt: number
}

/** Message shape persisted to localStorage (final text only — no reasoning trace). */
export interface PersistedMsg {
  id: string
  role: 'user' | 'assistant' | 'notice'
  content: string
  viaProvider?: string
}

/** A pending backend mutation. The UI updates optimistically; these drain in the
 *  background via the sync queue and survive reloads. */
export type SyncOp =
  | { kind: 'create'; convId: string; title: string; modelId: string }
  | { kind: 'rename'; convId: string; title: string }
  | { kind: 'delete'; convId: string }

export interface QueuedOp {
  id: string
  op: SyncOp
  attempts: number
  nextAttemptAt: number
  createdAt: number
}

