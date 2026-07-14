import { useState, useEffect, useRef, forwardRef, useImperativeHandle, type ReactNode, type ChangeEvent } from 'react'
import {
  submitSessionJob,
  getJob,
  getSessionStatus,
  startSession,
  extendSession,
  stopSession,
  IMAGE_JOB_POLL_INTERVAL_MS,
  type JobResult,
  type SessionStatus,
  type ImageParams,
} from '../api/client'
import AdvancedParams from './AdvancedParams'
import type { RefineHandler } from '../types'

export interface ModelDef {
  id: string
  title: string
  heading: string
  deployDescription: string
  notebookSlug: string
  defaultPrompt: string
}

export const WARMUP_STATUSES = new Set(['starting', 'installing', 'loading_model'])

interface InitImage {
  preview: string
  b64?: string
  jobId?: string
  label: string
  isRefinement: boolean
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

const ImageGenerator = forwardRef<
  { triggerRefine: RefineHandler },
  {
    model: ModelDef
    isConnected: boolean
    onSubmitted: () => void
    session: SessionStatus | null
    setSession: (s: SessionStatus | null) => void
    busyAction: 'start' | 'stop' | 'extend' | null
    setBusyAction: (action: 'start' | 'stop' | 'extend' | null) => void
  }
>(function ImageGenerator({ model, isConnected, onSubmitted, session, setSession, busyAction, setBusyAction }, ref) {
  const [prompt, setPrompt] = useState('')
  const [advParams, setAdvParams] = useState<ImageParams>({})
  const [initImage, setInitImage] = useState<InitImage | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [watchIds, setWatchIds] = useState<Set<string>>(new Set())
  const [submitting, setSubmitting] = useState(false)
  const [latestResult, setLatestResult] = useState<JobResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isAdvancedOpen, setIsAdvancedOpen] = useState(false)
  const [headerDuration, setHeaderDuration] = useState(30)
  const sessionBusy = busyAction !== null
  const [, setTick] = useState(0)

  // 1s ticker drives the live countdown — only run while there's one to show.
  useEffect(() => {
    if (!session?.alive || !session?.expires_at) return
    const id = setInterval(() => setTick((t) => t + 1), 1000)
    return () => clearInterval(id)
  }, [session?.alive, session?.expires_at])

  // Re-attach + poll server status for this model.
  useEffect(() => {
    let active = true
    setSession(null)
    async function poll() {
      try {
        const s = await getSessionStatus(model.id)
        if (active) setSession(s.status === 'none' ? null : s)
      } catch {
        /* transient — keep last known status */
      }
    }
    poll()
    const id = setInterval(poll, 3000)
    return () => {
      active = false
      clearInterval(id)
    }
  }, [model.id])

  async function handleHeaderStart() {
    if (sessionBusy) return
    setBusyAction('start')
    try {
      const s = await startSession(model.id, headerDuration, null)
      setSession({ status: s.status, alive: true, session_id: s.session_id, expires_at: s.expires_at })
      setError(null)
    } catch (err) {
      console.error('Failed to start session from header:', err)
      setError(err instanceof Error ? err.message : 'Failed to start session')
    } finally {
      setBusyAction(null)
    }
  }

  async function handleHeaderExtend() {
    if (!session?.session_id || sessionBusy) return
    setBusyAction('extend')
    try {
      const { expires_at } = await extendSession(session.session_id, 30)
      setSession({ ...session, expires_at })
      setError(null)
    } catch (err) {
      console.error('Failed to extend session:', err)
      setError(err instanceof Error ? err.message : 'Failed to extend session')
    } finally {
      setBusyAction(null)
    }
  }

  async function handleHeaderStop() {
    if (!session?.session_id || sessionBusy) return
    setBusyAction('stop')
    try {
      await stopSession(session.session_id)
      setSession({ ...session, status: 'stopping', alive: false })
      setError(null)
    } catch (err) {
      console.error('Failed to stop session:', err)
      setError(err instanceof Error ? err.message : 'Failed to stop session')
    } finally {
      setBusyAction(null)
    }
  }

  useImperativeHandle(ref, () => ({
    triggerRefine(job: JobResult, imageSrc: string) {
      setInitImage({
        preview: imageSrc,
        jobId: job.job_id,
        label: `Refining: "${(job.prompt ?? '').slice(0, 40)}${(job.prompt ?? '').length > 40 ? '…' : ''}"`,
        isRefinement: true,
      })
      setPrompt('')
      setError(null)
    },
  }))

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => {
      const dataUrl = ev.target?.result as string
      const img = new Image()
      img.onload = () => {
        const MAX = 768
        let { width, height } = img
        if (width > MAX || height > MAX) {
          const scale = Math.min(MAX / width, MAX / height)
          width = Math.round(width * scale)
          height = Math.round(height * scale)
        }
        const canvas = document.createElement('canvas')
        canvas.width = width
        canvas.height = height
        canvas.getContext('2d')!.drawImage(img, 0, 0, width, height)
        const resized = canvas.toDataURL('image/jpeg', 0.85)
        const b64 = resized.replace(/^data:[^;]+;base64,/, '')
        setInitImage({ preview: resized, b64, label: file.name, isRefinement: false })
      }
      img.src = dataUrl
    }
    reader.readAsDataURL(file)
    e.target.value = ''
  }

  function clearInitImage() {
    setInitImage(null)
    setAdvParams((prev) => {
      const next = { ...prev }
      delete next.strength
      return next
    })
  }

  // Clear local state when model changes (panel stays mounted, model prop changes).
  useEffect(() => {
    setPrompt('')
    setAdvParams({})
    setLatestResult(null)
    setError(null)
    setWatchIds(new Set())
    setInitImage(null)
  }, [model.id])

  const live = !!session?.alive
  // A session is "warm-routable" if it has a session_id — even during warmup.
  // Jobs queued now sit in Postgres and the kernel picks them up (via PostgREST) on entering serve loop.
  const hasSession = !!session?.alive

  // Poll submitted job IDs until each resolves; update inline preview with the latest.
  useEffect(() => {
    if (watchIds.size === 0) return
    let active = true
    const id = setInterval(async () => {
      if (!active) return
      const settled = new Set<string>()
      await Promise.all(
        [...watchIds].map(async (jid) => {
          try {
            const job = await getJob(jid)
            if (job.status === 'done') {
              settled.add(jid)
              setLatestResult((prev) => (!prev || job.status === 'done') ? job : prev)
            } else if (job.status === 'error') {
              // Keep polling if session is alive — kernel may overwrite error→done.
              const sessionAlive = !!session && (session.alive || hasSession)
              if (!sessionAlive) {
                settled.add(jid)
                setLatestResult((prev) => prev ?? job)
              }
            }
          } catch { /* keep polling */ }
        })
      )
      if (settled.size > 0) {
        setWatchIds((prev) => {
          const next = new Set(prev)
          settled.forEach((id) => next.delete(id))
          return next
        })
        onSubmitted()
      }
    }, IMAGE_JOB_POLL_INTERVAL_MS)
    return () => {
      active = false
      clearInterval(id)
    }
  }, [watchIds, onSubmitted, session, hasSession])

  const busy = submitting

  async function handleGenerate() {
    if (!prompt.trim()) { setError('Enter a prompt.'); return }
    if (busy) return
    setError(null)
    setSubmitting(true)
    try {
      const params = Object.keys(advParams).length > 0 ? advParams : undefined
      const initJobId = initImage?.isRefinement ? initImage.jobId : undefined
      const initB64 = !initJobId ? initImage?.b64 : undefined

      let sid = session?.alive ? session.session_id : undefined
      if (!sid) {
        setBusyAction('start')
        const s = await startSession(model.id, headerDuration, null)
        sid = s.session_id
        setSession({ status: s.status, alive: true, session_id: s.session_id, expires_at: s.expires_at })
        setBusyAction(null)
      }

      const { job_id } = await submitSessionJob(sid, prompt.trim(), params, initB64, initJobId)
      setWatchIds((prev) => new Set([...prev, job_id]))
      setPrompt('')
      setInitImage(null)
      onSubmitted()
    } catch (err) {
      setBusyAction(null)
      setError(err instanceof Error ? err.message : 'Generation failed')
    } finally {
      setSubmitting(false)
    }
  }

  function renderSessionControls(): ReactNode {
    const isStopping = session?.status === 'stopping' || busyAction === 'stop'
    const isWarming = !!session && WARMUP_STATUSES.has(session.status) && !isStopping
    const isRunning = session?.status === 'ready' && !isStopping

    if (isStopping) {
      return (
        <div className="flex items-center gap-1.5 shrink-0">
          <button
            type="button"
            disabled
            className="px-2.5 py-0.5 rounded-lg text-[10px] font-bold bg-theme-text text-theme-bg shadow-sm opacity-60 cursor-not-allowed select-none animate-pulse"
          >
            Stopping…
          </button>
        </div>
      )
    }

    if (isRunning || isWarming) {
      return (
        <div className="flex items-center gap-1.5 shrink-0">
          <button
            type="button"
            onClick={handleHeaderExtend}
            disabled={sessionBusy}
            className="px-2.5 py-0.5 rounded-lg text-[10px] font-semibold text-theme-text border border-theme-border/60 hover:bg-theme-surface-hover disabled:opacity-60 transition-colors cursor-pointer select-none"
          >
            +30
          </button>
          {isRunning ? (
            <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20 flex items-center gap-1.5 select-none">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              Session · ⏳ {countdown(session?.expires_at)} · {session?.images_done ?? 0}
            </span>
          ) : (
            <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20 flex items-center gap-1.5 select-none">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
              Warming
            </span>
          )}
          <button
            type="button"
            onClick={handleHeaderStop}
            disabled={sessionBusy}
            className="px-2.5 py-0.5 rounded-lg text-[10px] font-bold bg-theme-text text-theme-bg shadow-sm hover:opacity-90 disabled:opacity-60 cursor-pointer transition-colors"
          >
            Stop
          </button>
        </div>
      )
    }

    return (
      <div className="flex items-center gap-1.5 shrink-0">
        <select
          value={headerDuration}
          onChange={(e) => setHeaderDuration(parseInt(e.target.value, 10))}
          disabled={sessionBusy}
          className="px-2 py-0.5 rounded-lg text-[10px] bg-theme-bg border border-theme-border/60 text-theme-text disabled:opacity-60 focus:outline-none cursor-pointer"
        >
          <option value={30}>30 min</option>
          <option value={60}>60 min</option>
          <option value={120}>120 min</option>
        </select>
        <button
          type="button"
          onClick={handleHeaderStart}
          disabled={sessionBusy}
          className="px-2.5 py-0.5 rounded-lg text-[10px] font-bold bg-theme-text text-theme-bg shadow-sm hover:opacity-90 disabled:opacity-60 cursor-pointer transition-colors"
        >
          {busyAction === 'start' ? 'Starting…' : 'Start'}
        </button>
      </div>
    )
  }

  const resultIsImage = !!latestResult && (latestResult.mime ?? '').startsWith('image/')

  return (
    <div className="h-full flex flex-col rounded-xl border border-theme-border/60 bg-theme-surface overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-theme-border/40 bg-theme-surface-hover/30 shrink-0">
        <h2 className="text-xs font-semibold text-theme-text">{model.heading}</h2>
        {renderSessionControls()}
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3.5">

      <div className="space-y-2.5">
        {/* Row with Add Source Image on left, and Advanced Settings on right */}
        <div className="flex items-center justify-between px-1 shrink-0">
          {initImage ? (
            <div className="flex items-center gap-1.5 min-w-0">
              <img src={initImage.preview} alt="source" className="w-5 h-5 rounded object-cover shrink-0 border border-theme-border/60" />
              <span className="text-[10px] font-semibold text-theme-brand truncate max-w-[150px]">
                {initImage.isRefinement ? '↺ ' : '🖼 '}{initImage.label}
              </span>
              <button
                type="button"
                onClick={clearInitImage}
                className="w-4 h-4 flex items-center justify-center text-theme-text-muted hover:text-theme-text cursor-pointer"
                title="Remove source image"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" className="w-3.5 h-3.5">
                  <path d="M5.28 4.22a.75.75 0 0 0-1.06 1.06L6.94 8l-2.72 2.72a.75.75 0 1 0 1.06 1.06L8 9.06l2.72 2.72a.75.75 0 1 0 1.06-1.06L9.06 8l2.72-2.72a.75.75 0 0 0-1.06-1.06L8 6.94 5.28 4.22Z" />
                </svg>
              </button>
            </div>
          ) : (
            <>
              <input ref={fileInputRef} type="file" accept="image/*" className="hidden" onChange={handleFileChange} />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={!isConnected || busy}
                className="text-[11px] text-theme-text-muted hover:text-theme-text transition-colors cursor-pointer flex items-center gap-1 font-semibold disabled:opacity-50"
              >
                + Image
              </button>
            </>
          )}

          <button
            type="button"
            onClick={() => setIsAdvancedOpen((o) => !o)}
            className="text-[11px] text-theme-text-muted hover:text-theme-text transition-colors cursor-pointer font-semibold"
          >
            {isAdvancedOpen ? '− Advanced' : '+ Advanced'}
          </button>
        </div>

        <AdvancedParams modelId={model.id} onChange={setAdvParams} showStrength={!!initImage} open={isAdvancedOpen} />

        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          disabled={!isConnected || busy}
          placeholder={initImage?.isRefinement ? 'Describe what to change…' : 'Describe the image you want to generate...'}
          className="w-full h-20 px-3 py-2 rounded-xl text-sm bg-theme-bg border border-theme-border/60 text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-border disabled:opacity-60 resize-none"
        />
        <button
          type="button"
          onClick={handleGenerate}
          disabled={!isConnected || busy}
          className="w-full py-2.5 rounded-xl text-xs font-semibold bg-theme-brand text-theme-brand-text shadow-sm hover:opacity-90 disabled:opacity-60 cursor-pointer"
        >
          {submitting
            ? (session?.session_id ? 'Queuing…' : 'Starting session…')
            : live
              ? 'Generate'
              : 'Generate'}
        </button>

      </div>

      {!isConnected && (
        <div className="text-[10px] text-amber-600 dark:text-amber-400">
          Please connect to Kaggle and deploy the worker notebook above first.
        </div>
      )}

      {session?.status === 'error' && session.error && (
        <div className="p-3 rounded-xl border border-amber-200 dark:border-amber-900/50 bg-amber-50 dark:bg-amber-950/20 text-xs text-amber-800 dark:text-amber-300 font-medium break-words">
          ⚠ {session.error}
        </div>
      )}

      {latestResult && latestResult.status === 'done' && resultIsImage && latestResult.image_b64 && (
        <div className="space-y-1.5">
          <div className="text-[10px] font-medium text-theme-text-muted truncate">
            Latest: {latestResult.prompt}
          </div>
          <div className="rounded-xl overflow-hidden border border-theme-border/60 bg-theme-bg flex justify-center">
            <img
              src={`data:${latestResult.mime};base64,${latestResult.image_b64}`}
              alt={latestResult.prompt ?? ''}
              className="max-w-full h-auto object-contain max-h-[300px]"
            />
          </div>
          <div className="text-[10px] text-theme-text-muted">
            {latestResult.via ? `via ${latestResult.via}` : 'returned from Kaggle'}
          </div>
        </div>
      )}

      {latestResult && latestResult.status === 'done' && !resultIsImage && (
        <div className="p-2 rounded-lg bg-theme-bg border border-theme-border/60 text-theme-text text-xs break-words">
          {(() => {
            try { return latestResult.image_b64 ? atob(latestResult.image_b64) : '' }
            catch { return latestResult.image_b64 ?? '' }
          })()}
        </div>
      )}

      {((latestResult && latestResult.status === 'error') || error) && (
        <div className="p-3 rounded-xl border border-red-200 dark:border-red-900/50 bg-red-50 dark:bg-red-950/20 text-xs text-red-800 dark:text-red-300 font-medium break-words">
          {error ?? latestResult?.error ?? 'Generation failed'}
        </div>
      )}
      </div>
    </div>
  )
})

export default ImageGenerator
