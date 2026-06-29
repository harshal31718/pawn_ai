import { useEffect, useState } from 'react'
import {
  startSession,
  getSessionStatus,
  extendSession,
  stopSession,
  type SessionStatus,
} from '../api/client'

/**
 * Warm-session control bar for one model (Phase W.2). Owns the session lifecycle
 * — start (duration + optional image cap), live countdown, Extend, Stop — and
 * reports the current session up via `onSession` so the generator can route a
 * prompt to the warm kernel (fast) instead of a cold one-shot run. Re-attaches to
 * a live session on mount (survives refresh) by polling the server.
 */
const DURATIONS = [30, 60, 120]
const STATUS_POLL_MS = 3000

function countdown(expiresAt?: string | null): string {
  if (!expiresAt) return ''
  const ms = new Date(expiresAt).getTime() - Date.now()
  if (ms <= 0) return 'expired'
  const total = Math.floor(ms / 1000)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export default function SessionBar({
  model,
  onSession,
}: {
  model: string
  onSession: (s: SessionStatus | null) => void
}) {
  const [duration, setDuration] = useState(30)
  const [maxImages, setMaxImages] = useState('')
  const [session, setSession] = useState<SessionStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [, setTick] = useState(0) // 1s ticker for the live countdown

  // Report the current session up to the generator whenever it changes.
  useEffect(() => {
    onSession(session)
  }, [session, onSession])

  // Re-attach + poll server status for this model.
  useEffect(() => {
    let active = true
    setSession(null)
    async function poll() {
      try {
        const s = await getSessionStatus(model)
        if (active) setSession(s.status === 'none' ? null : s)
      } catch {
        /* transient — keep last known status */
      }
    }
    poll()
    const id = setInterval(poll, STATUS_POLL_MS)
    return () => {
      active = false
      clearInterval(id)
    }
  }, [model])

  const live = !!session?.alive

  // 1s ticker drives the live countdown — only run it while there's one to show.
  useEffect(() => {
    if (!live || !session?.expires_at) return
    const id = setInterval(() => setTick((t) => t + 1), 1000)
    return () => clearInterval(id)
  }, [live, session?.expires_at])

  const WARMUP_STATUSES = new Set(['starting', 'installing', 'loading_model'])
  const STARTUP_MESSAGES: Record<string, string> = {
    starting: 'Waiting for Kaggle GPU…',
    installing: 'Installing dependencies (1–2 min)…',
    loading_model: 'Loading model onto GPU (FLUX: ~7 min · SDXL: ~2 min)…',
  }
  const warmingUp = !!session && WARMUP_STATUSES.has(session.status)
  const ended = !!session && !live && !warmingUp

  async function handleStart() {
    if (session && !window.confirm(
      'A session already exists for this model. Starting a new one will stop it on Kaggle. Continue?'
    )) return
    setBusy(true)
    setError(null)
    try {
      const cap = maxImages.trim() ? Math.max(1, parseInt(maxImages, 10)) : null
      const s = await startSession(model, duration, cap)
      setSession({ status: s.status, alive: true, session_id: s.session_id, expires_at: s.expires_at })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start session')
    } finally {
      setBusy(false)
    }
  }

  async function handleExtend() {
    if (!session?.session_id) return
    setBusy(true)
    try {
      const { expires_at } = await extendSession(session.session_id, 30)
      setSession({ ...session, expires_at })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to extend')
    } finally {
      setBusy(false)
    }
  }

  async function handleStop() {
    if (!session?.session_id) return
    setBusy(true)
    try {
      await stopSession(session.session_id)
      setSession({ ...session, status: 'stopping', alive: false })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to stop')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-xl border border-theme-border/60 bg-theme-bg/50 p-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold text-theme-text">Warm session</span>
        {live && (
          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30">
            🟢 Warm · ⏳ {countdown(session?.expires_at)} · {session?.images_done ?? 0}
            {session?.max_images ? `/${session.max_images}` : ''}
          </span>
        )}
      </div>

      {!live && !warmingUp && (
        <div className="flex items-center gap-1.5 flex-wrap">
          <select
            value={duration}
            onChange={(e) => setDuration(parseInt(e.target.value, 10))}
            disabled={busy}
            className="px-2 py-1.5 rounded-lg text-[11px] bg-theme-surface border border-theme-border/60 text-theme-text disabled:opacity-60"
          >
            {DURATIONS.map((d) => (
              <option key={d} value={d}>{d} min</option>
            ))}
          </select>
          <input
            type="number"
            min={1}
            value={maxImages}
            onChange={(e) => setMaxImages(e.target.value)}
            disabled={busy}
            placeholder="max images"
            className="w-28 px-2 py-1.5 rounded-lg text-[11px] bg-theme-surface border border-theme-border/60 text-theme-text placeholder-theme-text-muted disabled:opacity-60"
          />
          <button
            type="button"
            onClick={handleStart}
            disabled={busy}
            className="px-3 py-1.5 rounded-lg text-[11px] font-semibold bg-theme-brand text-theme-brand-text shadow-sm hover:opacity-90 disabled:opacity-60 cursor-pointer"
          >
            {busy ? 'Starting…' : 'Start'}
          </button>
        </div>
      )}

      {warmingUp && (
        <div className="flex items-center gap-2 text-[11px] text-amber-600 dark:text-amber-400">
          <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse shrink-0" />
          <span>{STARTUP_MESSAGES[session!.status] ?? 'Starting…'}</span>
        </div>
      )}

      {live && (
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={handleExtend}
            disabled={busy}
            className="px-2.5 py-1 rounded-lg text-[11px] font-semibold text-theme-text border border-theme-border/60 hover:bg-theme-surface-hover disabled:opacity-60 cursor-pointer"
          >
            Extend +30
          </button>
          <button
            type="button"
            onClick={handleStop}
            disabled={busy}
            className="px-2.5 py-1 rounded-lg text-[11px] font-semibold text-theme-text border border-theme-border/60 hover:bg-theme-surface-hover disabled:opacity-60 cursor-pointer"
          >
            Stop
          </button>
        </div>
      )}

      {ended && (
        <div className="text-[11px] text-theme-text-muted">
          Session ended — start a new one to warm up again.
        </div>
      )}

      <p className="text-[10px] text-theme-text-muted leading-relaxed">
        First image pays the warm-up; later ones return in seconds while the session
        stays warm. Without a session, Generate runs a single cold image.
      </p>

      {error && <div className="text-[11px] text-red-600 dark:text-red-400">{error}</div>}
    </div>
  )
}
