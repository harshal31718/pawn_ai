/** Fail-proof background sync of conversation mutations.
 *
 * Mutations (create / rename / delete) are applied optimistically in the UI and
 * enqueued here. Ops are persisted to localStorage, retried with exponential
 * backoff, drained when connectivity returns, and survive reloads. The UI never
 * awaits the network for a mutation.
 */

import {
  createConversation,
  deleteConversation,
  updateConversationTitle,
} from '../api/client'
import type { QueuedOp, SyncOp } from '../types'

const QUEUE_VERSION = 1
const MAX_BACKOFF_MS = 30_000
const SYNC_ERROR_MSG = 'Some changes are not yet synced…'

interface SyncQueueOpts {
  /** Called when a create/rename op for a conversation succeeds (mark _synced). */
  onSynced: (convId: string) => void
  /** Called whenever the pending set or error status changes (drives UI). */
  notify: (pendingConvIds: Set<string>, status: string | null) => void
}

function keyFor(userId: string | null): string {
  return `pawn-syncq:v${QUEUE_VERSION}:${userId ?? 'anon'}`
}

function newOpId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
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
      this.queue = this.queue.filter((x) => x.op.convId !== op.convId)
      this.queue.push(this.wrap(op))
    } else if (op.kind === 'rename') {
      const existing = this.queue.find(
        (x) => x.op.convId === op.convId && x.op.kind === 'rename',
      )
      if (existing) {
        existing.op = op
        existing.attempts = 0
        existing.nextAttemptAt = 0
      } else {
        this.queue.push(this.wrap(op))
      }
    } else {
      // create — one per conv
      if (!this.queue.some((x) => x.op.convId === op.convId && x.op.kind === 'create')) {
        this.queue.push(this.wrap(op))
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
      await this.run(item.op)
      this.queue = this.queue.filter((x) => x.id !== item.id)
      if (item.op.kind === 'create' || item.op.kind === 'rename') {
        this.opts.onSynced(item.op.convId)
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

  private async run(op: SyncOp): Promise<void> {
    if (op.kind === 'create') {
      // Currently unused: New Chat is a draft that lazy-creates on first message
      // (see useConversationStore.createConversation / promoteDraft). Kept for
      // defensive completeness in case explicit pre-creation is reintroduced.
      await createConversation(op.title, op.modelId, op.convId)
    } else if (op.kind === 'rename') {
      await updateConversationTitle(op.convId, op.title)
    } else {
      await deleteConversation(op.convId) // 404 resolves as success in the client
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

  private pendingConvIds(): Set<string> {
    return new Set(this.queue.map((x) => x.op.convId))
  }

  private notify(): void {
    this.opts.notify(this.pendingConvIds(), this.status)
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
