import { useEffect, useRef, useState } from 'react'
import {
  startSession,
  getSessionStatus,
  submitSessionJob,
  stopSession,
  getJob,
  type SessionStatus,
  type JobResult,
} from '../api/client'

/**
 * Phase W warm-session control. Start a session (the kernel loads once, then
 * serves a Supabase work-loop), submit prompts, watch them complete in seconds
 * while the container stays warm, and stop. FLUX runs the real GPU serve-loop
 * (returns a PNG); SDXL runs the cheap CPU echo (returns text). The full session
 * bar + cross-model Generations monitor land in W.2.
 */
const DURATIONS = [30, 60, 120]
const STATUS_POLL_MS = 3000
const JOB_POLL_MS = 3000

function isImage(job: JobResult): boolean {
  return (job.mime ?? '').startsWith('image/')
}

function decodeText(job: JobResult): string {
  if (!job.image_b64) return ''
  try {
    return atob(job.image_b64)
  } catch {
    return job.image_b64
  }
}

function countdown(expiresAt?: string | null): string {
  if (!expiresAt) return ''
  const ms = new Date(expiresAt).getTime() - Date.now()
  if (ms <= 0) return 'expired'
  const total = Math.floor(ms / 1000)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export default function SessionPocPanel({ model }: { model: string }) {
  const [duration, setDuration] = useState(30)
  const [maxImages, setMaxImages] = useState('')
  const [session, setSession] = useState<SessionStatus | null>(null)
  const [prompt, setPrompt] = useState('a red apple on a wooden table')
  const [job, setJob] = useState<JobResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0) // drives the live countdown re-render
  const jobPollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Re-attach to any existing session for this model + poll its status.
  useEffect(() => {
    let active = true
    setSession(null)
    setJob(null)
    setError(null)
    async function poll() {
      try {
        const s = await getSessionStatus(model)
        if (active) setSession(s)
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

  // 1s ticker so the countdown updates smoothly between status polls.
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => () => { if (jobPollRef.current) clearInterval(jobPollRef.current) }, [])

  const live = !!session?.alive
  const starting = session?.status === 'starting'

  async function handleStart() {
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

  async function handleStop() {
    if (!session?.session_id) return
    setBusy(true)
    try {
      await stopSession(session.session_id)
      setSession({ ...session, status: 'stopping', alive: false })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to stop session')
    } finally {
      setBusy(false)
    }
  }

  async function handleSubmit() {
    if (!session?.session_id || !prompt.trim()) return
    setBusy(true)
    setError(null)
    setJob(null)
    try {
      const { job_id } = await submitSessionJob(session.session_id, prompt.trim())
      if (jobPollRef.current) clearInterval(jobPollRef.current)
      jobPollRef.current = setInterval(async () => {
        try {
          const j = await getJob(job_id)
          setJob(j)
          if (j.status === 'done' || j.status === 'error') {
            if (jobPollRef.current) clearInterval(jobPollRef.current)
            setBusy(false)
          }
        } catch {
          /* keep polling */
        }
      }, JOB_POLL_MS)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to submit job')
      setBusy(false)
    }
  }

  return (
    <div className="p-4 rounded-xl border border-theme-border/60 bg-theme-surface space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-semibold text-theme-text">Warm Session</h2>
        {session && session.status !== 'none' && (
          <span
            className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${
              live
                ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30'
                : 'bg-theme-bg text-theme-text-muted border-theme-border/60'
            }`}
          >
            {starting ? 'Starting' : live ? 'Warm' : session.status}
            {live && session.expires_at ? ` · ⏳ ${countdown(session.expires_at)}` : ''}
            {/* tick keeps the countdown above re-rendering */}
            <span className="hidden">{tick}</span>
          </span>
        )}
      </div>

      <p className="text-[11px] text-theme-text-muted leading-relaxed">
        The kernel loads once, then serves prompts from a Supabase work-loop —
        first image pays the warm-up, later ones return in seconds while it stays warm.
      </p>

      {!live && (
        <div className="flex items-center gap-2 flex-wrap">
          <select
            value={duration}
            onChange={(e) => setDuration(parseInt(e.target.value, 10))}
            disabled={busy}
            className="px-2.5 py-1.5 rounded-lg text-xs bg-theme-bg border border-theme-border/60 text-theme-text disabled:opacity-60"
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
            placeholder="max images (optional)"
            className="w-36 px-2.5 py-1.5 rounded-lg text-xs bg-theme-bg border border-theme-border/60 text-theme-text placeholder-theme-text-muted disabled:opacity-60"
          />
          <button
            type="button"
            onClick={handleStart}
            disabled={busy}
            className="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-theme-brand text-theme-brand-text shadow-sm hover:opacity-90 disabled:opacity-60 cursor-pointer"
          >
            {busy ? 'Starting…' : 'Start warm session'}
          </button>
        </div>
      )}

      {starting && (
        <div className="flex items-center gap-2 text-xs text-theme-text-muted">
          <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse shrink-0" />
          <span>Booting the kernel on Kaggle (a minute or so for the CPU POC)…</span>
        </div>
      )}

      {live && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-[11px] text-theme-text-muted">
            <span>🟢 Warm · {session?.images_done ?? 0} done{session?.max_images ? ` / ${session.max_images}` : ''}</span>
            <button
              type="button"
              onClick={handleStop}
              disabled={busy}
              className="px-2.5 py-1 rounded-lg text-[11px] font-semibold text-theme-text border border-theme-border/60 hover:bg-theme-surface-hover disabled:opacity-60 cursor-pointer"
            >
              Stop
            </button>
          </div>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            disabled={busy}
            className="w-full h-16 px-3 py-2 rounded-xl text-sm bg-theme-bg border border-theme-border/60 text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-border disabled:opacity-60 resize-none"
          />
          <button
            type="button"
            onClick={handleSubmit}
            disabled={busy || !prompt.trim()}
            className="w-full py-2 rounded-xl text-xs font-semibold bg-theme-brand text-theme-brand-text shadow-sm hover:opacity-90 disabled:opacity-60 cursor-pointer"
          >
            {busy && job?.status !== 'done' ? 'Generating…' : 'Generate (warm)'}
          </button>
        </div>
      )}

      {job && (
        <div className="text-[11px] text-theme-text-muted space-y-1">
          <div>
            Job <span className="font-mono">{job.status}</span>
            {job.via ? ` · via ${job.via}` : ''}
          </div>
          {job.status === 'done' && isImage(job) && job.image_b64 && (
            <div className="rounded-lg overflow-hidden border border-theme-border/60 bg-theme-bg flex justify-center">
              <img
                src={`data:${job.mime};base64,${job.image_b64}`}
                alt={job.prompt ?? 'generated image'}
                className="max-w-full h-auto object-contain max-h-[300px]"
              />
            </div>
          )}
          {job.status === 'done' && !isImage(job) && (
            <div className="p-2 rounded-lg bg-theme-bg border border-theme-border/60 text-theme-text break-words">
              {decodeText(job)}
            </div>
          )}
          {job.status === 'error' && job.error && (
            <div className="text-red-600 dark:text-red-400">{job.error}</div>
          )}
        </div>
      )}

      {!live && session?.status === 'ended' && (
        <div className="text-[11px] text-amber-600 dark:text-amber-400">
          Session ended — start a new one above.
        </div>
      )}

      {error && <div className="text-xs text-red-600 dark:text-red-400 break-words">{error}</div>}
    </div>
  )
}
