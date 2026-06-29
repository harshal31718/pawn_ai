import { useEffect, useState } from 'react'
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

function isImage(job: JobResult): boolean {
  return (job.mime ?? '').startsWith('image/')
}

/** Filename whose extension matches the data URL's image type (png/jpeg/webp…). */
function downloadName(dataUrl: string, id = 'image'): string {
  const m = dataUrl.match(/^data:image\/([\w.+-]+)/)
  return `pawn-${id}.${m ? m[1] : 'png'}`
}

const CHIP: Record<string, string> = {
  queued: 'bg-theme-bg text-theme-text-muted border-theme-border/60',
  running: 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30',
  done: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30',
  error: 'bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30',
}

function JobRow({ job, onView }: { job: JobResult; onView: (src: string, alt: string) => void }) {
  const [src, setSrc] = useState<string | null>(null)

  // Lazily fetch the image bytes for a done image job (the list omits them).
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

  const running = job.status === 'running'

  return (
    <div className="flex items-center gap-2.5 px-2.5 py-2 rounded-lg border border-theme-border/50 bg-theme-surface">
      {/* Thumbnail / placeholder */}
      <div className="w-10 h-10 shrink-0 rounded-md overflow-hidden bg-theme-bg border border-theme-border/50 flex items-center justify-center">
        {src ? (
          <img src={src} alt={job.prompt ?? ''} className="w-full h-full object-cover" />
        ) : (
          <span className="text-[9px] text-theme-text-muted">{job.status === 'done' && !isImage(job) ? 'txt' : '—'}</span>
        )}
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="text-[9px] font-semibold uppercase px-1.5 py-0.5 rounded bg-theme-bg border border-theme-border/60 text-theme-text-muted shrink-0">
            {job.model ?? '?'}
          </span>
          <span className="text-[11px] text-theme-text truncate">{job.prompt ?? ''}</span>
        </div>
        <div className="flex items-center gap-1.5 mt-0.5">
          <span
            className={`inline-flex items-center gap-1 text-[9px] font-semibold px-1.5 py-0.5 rounded-full border ${
              CHIP[job.status] ?? CHIP.queued
            }`}
          >
            {running && <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />}
            {job.status}
          </span>
          <span className="text-[9px] text-theme-text-muted">{relTime(job.created_at)}</span>
          {job.status === 'error' && job.error && (
            <span className="text-[9px] text-red-500 truncate" title={job.error}>{job.error}</span>
          )}
        </div>
      </div>

      {src && (
        <div className="flex items-center gap-1 shrink-0">
          <button
            type="button"
            onClick={() => onView(src, job.prompt ?? 'generation')}
            className="px-2 py-1 rounded-md text-[10px] font-semibold text-theme-text border border-theme-border/60 hover:bg-theme-surface-hover cursor-pointer"
          >
            View
          </button>
          <a
            href={src}
            download={downloadName(src, job.job_id)}
            className="px-2 py-1 rounded-md text-[10px] font-semibold text-theme-text border border-theme-border/60 hover:bg-theme-surface-hover cursor-pointer"
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
  const activeCount = jobs.filter((j) => j.status === 'queued' || j.status === 'running').length

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
            {activeCount > 0 && ` · ${activeCount} active`}
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
            jobs.map((j) => <JobRow key={j.job_id} job={j} onView={(src, alt) => setLightbox({ src, alt })} />)
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
