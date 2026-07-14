/** Fail-proof background sync of conversation mutations.
 *
 * Mutations (create / rename / delete) are applied optimistically in the UI and
 * enqueued here. Ops are persisted to localStorage, retried with exponential
 * backoff, drained when connectivity returns, and survive reloads. The UI never
 * awaits the network for a mutation.
 */

import {
  createConversation,
  createProject as createProjectApi,
  deleteConversation,
  deleteProject as deleteProjectApi,
  moveChatToProject,
  removeChatFromProject,
  renameProject as renameProjectApi,
  updateConversationTitle,
} from '../api/client'
import type { QueuedOp, SyncOp } from '../types'

const QUEUE_VERSION = 1
const MAX_BACKOFF_MS = 30_000
const SYNC_ERROR_MSG = 'Some changes are not yet synced…'

interface SyncQueueOpts {
  /** Called when a create/rename op for a conversation succeeds (mark _synced). */
  onSynced: (convId: string) => void
  /** Called when a createProject/renameProject op succeeds (mark _synced). */
  onProjectSynced?: (projectId: string) => void
  /** Called whenever the pending set or error status changes (drives UI). Ids
   *  cover both conversations and projects — distinct UUID namespaces, so a
   *  single set is safe for `pendingIds.has(id)` checks either way. */
  notify: (pendingIds: Set<string>, status: string | null) => void
  /** Resolve which project a chat currently belongs to (null = standalone).
   *  Needed only for `moveChat` ops whose target `projectId` is null
   *  (move-out): the backend's move-out route is scoped by the *source*
   *  project (`DELETE /projects/{id}/chats/{conv_id}`), which the op itself
   *  doesn't carry (see QueuedOp.fromProjectId). */
  resolveChatProject: (convId: string) => string | null
}

function keyFor(userId: string | null): string {
  return `pawn-syncq:v${QUEUE_VERSION}:${userId ?? 'anon'}`
}

function newOpId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

function opConvId(op: SyncOp): string | undefined {
  switch (op.kind) {
    case 'create':
    case 'rename':
    case 'delete':
    case 'moveChat':
      return op.convId
    default:
      return undefined
  }
}

function opProjectId(op: SyncOp): string | undefined {
  switch (op.kind) {
    case 'createProject':
    case 'renameProject':
    case 'deleteProject':
      return op.projectId
    case 'moveChat':
      return op.projectId ?? undefined
    default:
      return undefined
  }
}

export class SyncQueue {
  private userId: string | null
  private opts: SyncQueueOpts
  private queue: QueuedOp[] = []
  private processing = false
  private timer: ReturnType<typeof setTimeout> | undefined
  private status: string | null = null

  constructor(userId: string | null, opts: SyncQueueOpts) {
    this.userId = userId
    this.opts = opts
  }

  start(): void {
    this.queue = this.load()
    window.addEventListener('online', this.onOnline)
    this.notify()
    void this.process()
  }

  stop(): void {
    window.removeEventListener('online', this.onOnline)
    if (this.timer) clearTimeout(this.timer)
  }

  enqueue(op: SyncOp): void {
    if (op.kind === 'delete') {
      // A delete supersedes any pending create/rename for this conv. If the conv
      // was never materialized server-side the DELETE 404s (treated as success).
      this.queue = this.queue.filter((x) => opConvId(x.op) !== op.convId)
      this.queue.push(this.wrap(op))
    } else if (op.kind === 'rename') {
      const existing = this.queue.find(
        (x) => x.op.kind === 'rename' && x.op.convId === op.convId,
      )
      if (existing) {
        existing.op = op
        existing.attempts = 0
        existing.nextAttemptAt = 0
      } else {
        this.queue.push(this.wrap(op))
      }
    } else if (op.kind === 'create') {
      // one per conv
      if (!this.queue.some((x) => x.op.kind === 'create' && x.op.convId === op.convId)) {
        this.queue.push(this.wrap(op))
      }
    } else if (op.kind === 'deleteProject') {
      // Supersedes any pending create/rename/move-in for this project — it's
      // being destroyed, those ops are now moot.
      this.queue = this.queue.filter((x) => opProjectId(x.op) !== op.projectId)
      this.queue.push(this.wrap(op))
    } else if (op.kind === 'renameProject') {
      const existing = this.queue.find(
        (x) => x.op.kind === 'renameProject' && x.op.projectId === op.projectId,
      )
      if (existing) {
        existing.op = op
        existing.attempts = 0
        existing.nextAttemptAt = 0
      } else {
        this.queue.push(this.wrap(op))
      }
    } else if (op.kind === 'createProject') {
      if (!this.queue.some((x) => x.op.kind === 'createProject' && x.op.projectId === op.projectId)) {
        this.queue.push(this.wrap(op))
      }
    } else {
      // moveChat — only the latest desired placement for this conv matters.
      const existing = this.queue.find(
        (x) => x.op.kind === 'moveChat' && x.op.convId === op.convId,
      )
      if (existing) {
        existing.op = op
        existing.attempts = 0
        existing.nextAttemptAt = 0
        // Resolve fromProjectId only the first time a move-out is queued for
        // this conv. resolveChatProject reads the store's live ref, which by
        // now reflects THIS op's own optimistic update (project_id already
        // cleared) — recomputing on a coalesced re-enqueue (e.g. a repeated
        // remove-from-project click) would read null and clobber the correct
        // source project captured by the original enqueue.
        if (op.projectId === null && existing.fromProjectId === undefined) {
          existing.fromProjectId = this.opts.resolveChatProject(op.convId)
        }
      } else {
        const wrapped = this.wrap(op)
        if (op.projectId === null) wrapped.fromProjectId = this.opts.resolveChatProject(op.convId)
        this.queue.push(wrapped)
      }
    }
    this.persist()
    this.notify()
    void this.process()
  }

  // ── internals ────────────────────────────────────────────────────────────

  private wrap(op: SyncOp): QueuedOp {
    return { id: newOpId(), op, attempts: 0, nextAttemptAt: 0, createdAt: Date.now() }
  }

  private onOnline = () => {
    void this.process()
  }

  private async process(): Promise<void> {
    if (this.processing) return
    if (typeof navigator !== 'undefined' && navigator.onLine === false) return

    const now = Date.now()
    const item = this.queue.find((x) => x.nextAttemptAt <= now)
    if (!item) {
      this.rearm()
      return
    }

    this.processing = true
    try {
      await this.run(item)
      this.queue = this.queue.filter((x) => x.id !== item.id)
      if (item.op.kind === 'create' || item.op.kind === 'rename' || item.op.kind === 'moveChat') {
        this.opts.onSynced(item.op.convId)
      } else if (item.op.kind === 'createProject' || item.op.kind === 'renameProject') {
        this.opts.onProjectSynced?.(item.op.projectId)
      }
      this.setStatus(this.queue.length ? this.status : null)
      this.persist()
    } catch {
      item.attempts += 1
      item.nextAttemptAt =
        Date.now() + Math.min(MAX_BACKOFF_MS, 2 ** item.attempts * 1000) + Math.random() * 500
      this.setStatus(SYNC_ERROR_MSG)
      this.persist()
    } finally {
      this.processing = false
      this.notify()
      if (this.queue.length) {
        // Process the next ready op immediately, else re-arm a backoff timer.
        const ready = this.queue.some((x) => x.nextAttemptAt <= Date.now())
        if (ready) void this.process()
        else this.rearm()
      }
    }
  }

  private async run(item: QueuedOp): Promise<void> {
    const op = item.op
    if (op.kind === 'create') {
      // Currently unused: New Chat is a draft that lazy-creates on first message
      // (see useConversationStore.createConversation / promoteDraft). Kept for
      // defensive completeness in case explicit pre-creation is reintroduced.
      await createConversation(op.title, op.modelId, op.convId)
    } else if (op.kind === 'rename') {
      await updateConversationTitle(op.convId, op.title)
    } else if (op.kind === 'delete') {
      await deleteConversation(op.convId) // 404 resolves as success in the client
    } else if (op.kind === 'createProject') {
      await createProjectApi(op.name, op.projectId)
    } else if (op.kind === 'renameProject') {
      await renameProjectApi(op.projectId, op.name)
    } else if (op.kind === 'deleteProject') {
      await deleteProjectApi(op.projectId) // 404 resolves as success in the client
    } else {
      // moveChat
      if (op.projectId) {
        await moveChatToProject(op.projectId, op.convId)
      } else if (item.fromProjectId) {
        await removeChatFromProject(item.fromProjectId, op.convId) // 404 resolves as success
      }
      // fromProjectId falsy with a null target means the chat was already
      // standalone when this op was queued — nothing to do.
    }
  }

  private rearm(): void {
    if (this.timer) clearTimeout(this.timer)
    if (!this.queue.length) return
    const next = Math.min(...this.queue.map((x) => x.nextAttemptAt))
    const delay = Math.max(0, next - Date.now())
    this.timer = setTimeout(() => void this.process(), delay)
  }

  private setStatus(status: string | null): void {
    this.status = status
  }

  private pendingIds(): Set<string> {
    const ids = new Set<string>()
    for (const x of this.queue) {
      const cid = opConvId(x.op)
      if (cid) ids.add(cid)
      const pid = opProjectId(x.op)
      if (pid) ids.add(pid)
    }
    return ids
  }

  private notify(): void {
    this.opts.notify(this.pendingIds(), this.status)
  }

  private persist(): void {
    try {
      localStorage.setItem(keyFor(this.userId), JSON.stringify(this.queue))
    } catch {
      // best-effort
    }
  }

  private load(): QueuedOp[] {
    try {
      const raw = localStorage.getItem(keyFor(this.userId))
      if (!raw) return []
      const parsed = JSON.parse(raw)
      if (!Array.isArray(parsed)) return []
      // Reset backoff timers so a reloaded queue drains promptly.
      return (parsed as QueuedOp[]).map((x) => ({ ...x, nextAttemptAt: 0 }))
    } catch {
      return []
    }
  }
}
