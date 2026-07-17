import { describe, it, expect } from 'vitest'
import { sortForDisplay, dequeueOrder } from './GenerationsPanel'
import type { JobResult } from '../api/client'

function job(id: string, status: string, extra: Partial<JobResult> = {}): JobResult {
  return { job_id: id, status, created_at: extra.created_at ?? new Date(0).toISOString(), ...extra }
}

describe('G1 — dequeueOrder', () => {
  it('orders untouched (never-reordered) jobs by created_at ascending -- plain FIFO', () => {
    const a = job('a', 'queued', { created_at: '2026-01-01T00:00:02Z' })
    const b = job('b', 'queued', { created_at: '2026-01-01T00:00:01Z' })
    const c = job('c', 'queued', { created_at: '2026-01-01T00:00:03Z' })
    expect(dequeueOrder([a, b, c]).map((j) => j.job_id)).toEqual(['b', 'a', 'c'])
  })

  it('orders reordered jobs by queue_pos ascending, ignoring created_at', () => {
    const a = job('a', 'queued', { queue_pos: 3000, created_at: '2026-01-01T00:00:01Z' })
    const b = job('b', 'queued', { queue_pos: 1000, created_at: '2026-01-01T00:00:03Z' })
    const c = job('c', 'queued', { queue_pos: 2000, created_at: '2026-01-01T00:00:02Z' })
    expect(dequeueOrder([a, b, c]).map((j) => j.job_id)).toEqual(['b', 'c', 'a'])
  })
})

describe('G1 — sortForDisplay', () => {
  it('groups queued before running before done/error', () => {
    const q = job('q', 'queued')
    const r = job('r', 'running')
    const d = job('d', 'done')
    const e = job('e', 'error')
    const order = sortForDisplay([d, r, e, q]).map((j) => j.job_id)
    expect(order.indexOf('q')).toBeLessThan(order.indexOf('r'))
    expect(order.indexOf('r')).toBeLessThan(order.indexOf('d'))
    expect(order.indexOf('r')).toBeLessThan(order.indexOf('e'))
  })

  it('within the queued group, displays newest-request at top and next-to-execute at bottom', () => {
    const older = job('older', 'queued', { created_at: '2026-01-01T00:00:01Z' })
    const newer = job('newer', 'queued', { created_at: '2026-01-01T00:00:02Z' })
    const order = sortForDisplay([older, newer]).map((j) => j.job_id)
    // newer request displays first (top); older (next to execute under plain
    // FIFO) displays last (bottom) -- "bottom executes first".
    expect(order).toEqual(['newer', 'older'])
  })

  it('keeps done/error sorted newest-first, unchanged from prior behavior', () => {
    const older = job('older', 'done', { created_at: '2026-01-01T00:00:01Z' })
    const newer = job('newer', 'error', { created_at: '2026-01-01T00:00:02Z' })
    expect(sortForDisplay([older, newer]).map((j) => j.job_id)).toEqual(['newer', 'older'])
  })

  it('does not interleave queued jobs from two different sessions', () => {
    const s1a = job('s1a', 'queued', { session_id: 's1', created_at: '2026-01-01T00:00:01Z' })
    const s2a = job('s2a', 'queued', { session_id: 's2', created_at: '2026-01-01T00:00:02Z' })
    const s1b = job('s1b', 'queued', { session_id: 's1', created_at: '2026-01-01T00:00:03Z' })
    const order = sortForDisplay([s1a, s2a, s1b]).map((j) => j.job_id)
    // s1's group contains the single newest job (s1b) so it displays first;
    // within s1, newest (s1b) at top, oldest (s1a) at bottom -- s2's group
    // (only s2a) displays last. Groups never interleave.
    expect(order).toEqual(['s1b', 's1a', 's2a'])
  })
})
