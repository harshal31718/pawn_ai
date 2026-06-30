import { useEffect, useRef, useState } from 'react'
import { getJob, type JobResult } from '../api/client'

/**
 * The Generations monitor (Phase W.2) — a collapsible panel listing every job
 * across models and sessions, newest first. Server-backed, so results survive a
 * refresh/tab-switch (the lost-result a user navigated away from reappears here).
 * Image bytes are NOT in the list payload; each done image job lazily fetches its
 * PNG via getJob and caches it for a thumbnail + lightbox + download.
 */
function relTime(iso?: string | null): string {
  if (!iso) return ''
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

function fmtDuration(totalSecs: number): string {
  const m = Math.floor(totalSecs / 60)
  const s = totalSecs % 60
  return `${m}m ${String(s).padStart(2, '0')}s`
}

function isImage(job: JobResult): boolean {
  return (job.mime ?? '').startsWith('image/')
}

function downloadName(dataUrl: string, id = 'image'): string {
  const m = dataUrl.match(/^data:image\/([\w.+-]+)/)
  return `pawn-${id}.${m ? m[1] : 'png'}`
}

// Inverse of ImageLabPage's STYLE_PRESET_KEYS map: value → display label.
const STYLE_PRESET_LABELS: Record<string, string> = {
  photorealistic: 'Photorealistic',
  cinematic: 'Cinematic',
  anime: 'Anime',
  oil_painting: 'Oil Painting',
  sketch: 'Sketch',
}

const CHIP: Record<string, string> = {
  queued: 'bg-theme-bg text-theme-text-muted border-theme-border/60',
  running: 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30',
  done: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30',
  error: 'bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30',
}

function JobRow({ job, onView }: { job: JobResult; onView: (src: string, alt: string) => void }) {
  const [src, setSrc] = useState<string | null>(null)
  const [nowMs, setNowMs] = useState(() => Date.now())
  const [copied, setCopied] = useState(false)
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Lazily fetch image bytes for done image jobs (list omits them).
  useEffect(() => {
    let active = true
    if (job.status === 'done' && isImage(job)) {
      getJob(job.job_id)
        .then((full) => {
          if (active && full.image_b64) setSrc(`data:${full.mime};base64,${full.image_b64}`)
        })
        .catch(() => {})
    }
    return () => {
      active = false
    }
  }, [job.job_id, job.status, job.mime])

  // Tick the elapsed clock every second for running jobs only.
  useEffect(() => {
    if (job.status !== 'running' || !job.started_at) return
    const id = setInterval(() => setNowMs(Date.now()), 1000)
    return () => clearInterval(id)
  }, [job.status, job.started_at])

  // Cancel the copy-confirmed timer on unmount.
  useEffect(() => {
    return () => {
      if (copyTimer.current) clearTimeout(copyTimer.current)
    }
  }, [])

  // Compute generation time string.
  let genTime: string | null = null
  if (job.started_at) {
    if (job.status === 'running') {
      const elapsed = Math.max(0, Math.floor((nowMs - new Date(job.started_at).getTime()) / 1000))
      genTime = fmtDuration(elapsed)
    } else if ((job.status === 'done' || job.status === 'error') && job.done_at) {
      const elapsed = Math.max(
        0,
        Math.floor((new Date(job.done_at).getTime() - new Date(job.started_at).getTime()) / 1000),
      )
      genTime = fmtDuration(elapsed)
    }
  }

  const presetKey = typeof job.params?.style_preset === 'string' ? job.params.style_preset : null
  const stylePreset = presetKey ? (STYLE_PRESET_LABELS[presetKey] ?? presetKey) : null

  const running = job.status === 'running'

  function handleCopy() {
    navigator.clipboard
      .writeText(job.prompt ?? '')
      .then(() => {
        setCopied(true)
        if (copyTimer.current) clearTimeout(copyTimer.current)
        copyTimer.current = setTimeout(() => setCopied(false), 1500)
      })
      .catch(() => {})
  }

  return (
    <div className="flex items-center gap-2.5 px-2.5 py-2 rounded-lg border border-theme-border/50 bg-theme-surface">
      {/* Thumbnail / placeholder */}
      <div className="w-10 h-10 shrink-0 rounded-md overflow-hidden bg-theme-bg border border-theme-border/50 flex items-center justify-center">
        {src ? (
          <img src={src} alt={job.prompt ?? ''} className="w-full h-full object-cover" />
        ) : (
          <span className="text-[9px] text-theme-text-muted">
            {job.status === 'done' && !isImage(job) ? 'txt' : '—'}
          </span>
        )}
      </div>

      {/* Content column */}
      <div className="min-w-0 flex-1">
        {/* Line 1: model badge · prompt · style preset pill · copy button */}
        <div className="flex items-center gap-1.5">
          <span className="text-[9px] font-semibold uppercase px-1.5 py-0.5 rounded bg-theme-bg border border-theme-border/60 text-theme-text-muted shrink-0">
            {job.model ?? '?'}
          </span>
          <span className="text-[11px] text-theme-text truncate flex-1">{job.prompt ?? ''}</span>
          {stylePreset && (
            <span className="shrink-0 text-[10px] px-1.5 py-0.5 rounded-full border bg-theme-brand/10 text-theme-brand border-theme-brand/20">
              {stylePreset}
            </span>
          )}
          <button
            type="button"
            title="Copy prompt"
            onClick={handleCopy}
            className="shrink-0 w-6 h-6 flex items-center justify-center rounded text-theme-text-muted hover:text-theme-text cursor-pointer"
          >
            {copied ? (
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 16 16"
                fill="currentColor"
                className="w-3.5 h-3.5 text-emerald-500"
              >
                <path
                  fillRule="evenodd"
                  d="M12.416 3.376a.75.75 0 0 1 .208 1.04l-5 7.5a.75.75 0 0 1-1.154.114l-3-3a.75.75 0 0 1 1.06-1.06l2.353 2.353 4.493-6.74a.75.75 0 0 1 1.04-.207Z"
                  clipRule="evenodd"
                />
              </svg>
            ) : (
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 16 16"
                fill="currentColor"
                className="w-3.5 h-3.5"
              >
                <path
                  fillRule="evenodd"
                  d="M11 3.5A1.5 1.5 0 0 0 9.5 2h-5A1.5 1.5 0 0 0 3 3.5v8A1.5 1.5 0 0 0 4.5 13h.25a.75.75 0 0 0 0-1.5H4.5a.25.25 0 0 1-.25-.25v-8a.25.25 0 0 1 .25-.25h5a.25.25 0 0 1 .25.25V4a.75.75 0 0 0 1.5 0v-.5Zm1.5 2A1.5 1.5 0 0 1 14 7v6.5A1.5 1.5 0 0 1 12.5 15h-5A1.5 1.5 0 0 1 6 13.5V7A1.5 1.5 0 0 1 7.5 5.5h5Z"
                  clipRule="evenodd"
                />
              </svg>
            )}
          </button>
        </div>

        {/* Line 2: status chip · created time · error · gen time (right-aligned) */}
        <div className="flex items-center justify-between mt-0.5">
          <div className="flex items-center gap-1.5 min-w-0 flex-1">
            <span
              className={`inline-flex items-center gap-1 text-[9px] font-semibold px-1.5 py-0.5 rounded-full border shrink-0 ${
                CHIP[job.status] ?? CHIP.queued
              }`}
            >
              {running && <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />}
              {job.status}
            </span>
            <span className="text-[9px] text-theme-text-muted shrink-0">{relTime(job.created_at)}</span>
            {job.status === 'error' && job.error && (
              <span className="text-[9px] text-red-500 truncate" title={job.error}>
                {job.error}
              </span>
            )}
          </div>
          {genTime && (
            <span className="text-[9px] text-theme-text-muted shrink-0 ml-2">⏱ {genTime}</span>
          )}
        </div>
      </div>

      {/* View + Download stacked vertically at far right */}
      {src && (
        <div className="flex flex-col items-stretch gap-1 shrink-0">
          <button
            type="button"
            onClick={() => onView(src, job.prompt ?? 'generation')}
            className="px-2 py-1 rounded-md text-[10px] font-semibold text-theme-text border border-theme-border/60 hover:bg-theme-surface-hover cursor-pointer text-center"
          >
            View
          </button>
          <a
            href={src}
            download={downloadName(src, job.job_id)}
            className="px-2 py-1 rounded-md text-[10px] font-semibold text-theme-text border border-theme-border/60 hover:bg-theme-surface-hover cursor-pointer text-center"
          >
            Download
          </a>
        </div>
      )}
    </div>
  )
}

export default function GenerationsPanel({ jobs }: { jobs: JobResult[] }) {
  const [open, setOpen] = useState(true)
  const [lightbox, setLightbox] = useState<{ src: string; alt: string } | null>(null)

  const runningCount = jobs.filter((j) => j.status === 'running').length
  const queuedCount = jobs.filter((j) => j.status === 'queued').length

  return (
    <div className="rounded-xl border border-theme-border/60 bg-theme-surface">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-4 py-2.5 cursor-pointer"
      >
        <span className="text-xs font-semibold text-theme-text">
          Generations
          <span className="ml-1.5 text-[10px] font-normal text-theme-text-muted">
            {jobs.length}
            {runningCount > 0 && (
              <span className="text-amber-500 dark:text-amber-400"> · {runningCount} running</span>
            )}
            {queuedCount > 0 && <> · {queuedCount} queued</>}
          </span>
        </span>
        <svg
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth={2}
          stroke="currentColor"
          className={`w-3.5 h-3.5 text-theme-text-muted transition-transform ${open ? 'rotate-180' : ''}`}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
        </svg>
      </button>

      {open && (
        <div className="px-3 pb-3 space-y-1.5 max-h-[340px] overflow-y-auto">
          {jobs.length === 0 ? (
            <div className="text-[11px] text-theme-text-muted px-1 py-2">
              No generations yet. Generate an image — it'll appear here and persist across refreshes.
            </div>
          ) : (
            jobs.map((j) => (
              <JobRow key={j.job_id} job={j} onView={(src, alt) => setLightbox({ src, alt })} />
            ))
          )}
        </div>
      )}

      {lightbox && (
        <div
          className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6"
          onClick={() => setLightbox(null)}
        >
          <div className="max-w-2xl w-full space-y-3" onClick={(e) => e.stopPropagation()}>
            <img src={lightbox.src} alt={lightbox.alt} className="w-full h-auto rounded-xl shadow-2xl" />
            <div className="flex items-center justify-between">
              <span className="text-xs text-white/80 truncate">{lightbox.alt}</span>
              <div className="flex items-center gap-2">
                <a
                  href={lightbox.src}
                  download={downloadName(lightbox.src)}
                  className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-white/15 text-white hover:bg-white/25 cursor-pointer"
                >
                  Download
                </a>
                <button
                  type="button"
                  onClick={() => setLightbox(null)}
                  className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-white/15 text-white hover:bg-white/25 cursor-pointer"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
