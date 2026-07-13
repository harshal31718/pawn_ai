export interface TraceEvent {
  type: 'step' | 'memory_hit' | 'model_call' | 'provider_switch'
  label?: string
  detail?: string
  summary?: string
  scope?: 'chat' | 'project'
  sourceConvId?: string
  model?: string
  purpose?: string
  from?: string
  to?: string
  timestamp: string
}

export interface Citation {
  url: string
  title: string
}

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'notice'
  content: string
  trace?: TraceEvent[]
  citations?: Citation[]
  viaProvider?: string
}

export interface ChatState {
  messages: Message[]
  isStreaming: boolean
}

// ─── Client-side conversation cache + sync types ─────────────────────────────

import type { ConversationMeta, JobResult, Project } from './api/client'

export type RefineHandler = (job: JobResult, imageSrc: string) => void

/** A conversation in the client cache. `_synced` is false until the backend has
 *  acknowledged the conversation exists; `_localUpdatedAt` is a client clock used
 *  to decide whether a server title should overwrite a local (user) rename. */
export interface CachedConversation extends ConversationMeta {
  _synced: boolean
  _localUpdatedAt: number
}

/** A project in the client cache — same `_synced`/`_localUpdatedAt` optimistic-UI
 *  shape as `CachedConversation`. */
export interface CachedProject extends Project {
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
 *  background via the sync queue and survive reloads.
 *
 *  Project ops key on `projectId` (mirroring conversation ops keying on `convId`)
 *  so the queue's per-entity dedup/supersede logic can treat them uniformly.
 *  `moveChat` carries both ids: `projectId: string | null` means "move to
 *  standalone" (null = out), a real id means "move into that project" (in). */
export type SyncOp =
  | { kind: 'create'; convId: string; title: string; modelId: string }
  | { kind: 'rename'; convId: string; title: string }
  | { kind: 'delete'; convId: string }
  | { kind: 'createProject'; projectId: string; name: string }
  | { kind: 'renameProject'; projectId: string; name: string }
  | { kind: 'deleteProject'; projectId: string }
  | { kind: 'moveChat'; convId: string; projectId: string | null }

export interface QueuedOp {
  id: string
  op: SyncOp
  attempts: number
  nextAttemptAt: number
  createdAt: number
  /** Resolved once, at enqueue time, for a `moveChat` op whose `projectId` is
   *  null (move-out): the project the chat was in when the op was queued.
   *  The backend's move-out route is `DELETE /projects/{id}/chats/{conv_id}`
   *  and needs that source id — the op itself only carries the *target*
   *  (null), per plan_memory_scoping.md's locked SyncOp shape, so this
   *  execution detail is carried alongside the op instead of inside it. */
  fromProjectId?: string | null
}

// ─── Image generation presets ─────────────────────────────────────────────────

export const STYLE_PRESETS = [
  { key: 'photorealistic', label: 'Photorealistic' },
  { key: 'cinematic',      label: 'Cinematic' },
  { key: 'anime',          label: 'Anime' },
  { key: 'oil_painting',   label: 'Oil Painting' },
  { key: 'sketch',         label: 'Sketch' },
] as const

/** label → key  (used by ImageLabPage to build the submit payload) */
export const STYLE_PRESET_KEY_MAP: Record<string, string> =
  Object.fromEntries(STYLE_PRESETS.map(({ key, label }) => [label, key]))

/** key → label  (used by GenerationsPanel to display the style chip) */
export const STYLE_PRESET_LABEL_MAP: Record<string, string> =
  Object.fromEntries(STYLE_PRESETS.map(({ key, label }) => [key, label]))

