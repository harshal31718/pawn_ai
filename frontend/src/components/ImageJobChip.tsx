import { useEffect, useRef, useState } from 'react'
import { getJob, type JobResult } from '../api/client'

interface Props {
  jobId: string
}

const POLL_INTERVAL_MS = 3000
const TERMINAL_STATUSES = new Set(['done', 'error'])

/** F-1 — inline chip for a generate_image tool call: polls GET /generate/job/{id}
 *  (same client helper Image Lab's own job monitor uses) until the job reaches a
 *  terminal state, then swells into the rendered image (or a plain error line).
 *  Lives inside TraceView's ToolCard, always visible regardless of the card's
 *  own collapsed/expanded state — the image itself is the point, not something
 *  to hide behind a chevron. */
export default function ImageJobChip({ jobId }: Props) {
  const [job, setJob] = useState<JobResult | null>(null)
  const [pollError, setPollError] = useState<string | null>(null)
  const stopped = useRef(false)

  useEffect(() => {
    stopped.current = false
    let timer: ReturnType<typeof setTimeout> | undefined

    async function poll() {
      if (stopped.current) return
      try {
        const result = await getJob(jobId)
        if (stopped.current) return
        setJob(result)
        setPollError(null)
        if (!TERMINAL_STATUSES.has(result.status)) {
          timer = setTimeout(poll, POLL_INTERVAL_MS)
        }
      } catch (err) {
        if (stopped.current) return
        // Transient network hiccup -- keep polling rather than giving up on
        // one failed request (matches the Image Lab monitor's own tolerance).
        setPollError(err instanceof Error ? err.message : 'Failed to check job status')
        timer = setTimeout(poll, POLL_INTERVAL_MS)
      }
    }

    void poll()
    return () => {
      stopped.current = true
      if (timer) clearTimeout(timer)
    }
  }, [jobId])

  if (!job) {
    return (
      <div className="flex items-center gap-2 mt-1 text-[11px] text-theme-ai-bubble-text/60">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse shrink-0" />
        <span>Starting generation…</span>
      </div>
    )
  }

  if (job.status === 'error') {
    return (
      <div className="mt-1 text-[11px] text-red-400">
        Image generation failed{job.error ? `: ${job.error}` : '.'}
      </div>
    )
  }

  if (job.status === 'done' && job.image_b64) {
    const mime = job.mime || 'image/png'
    const src = `data:${mime};base64,${job.image_b64}`
    const ext = mime.split('/')[1] || 'png'
    return (
      <div className="mt-1 flex flex-col items-start gap-1">
        <img
          src={src}
          alt={job.prompt || 'Generated image'}
          className="rounded-lg max-w-[240px] max-h-[240px] border border-theme-ai-bubble-text/10"
        />
        <a
          href={src}
          download={`pawn-${jobId}.${ext}`}
          className="px-2 py-1 rounded-md text-[10px] font-semibold text-theme-ai-bubble-text border border-theme-ai-bubble-text/20 hover:bg-theme-ai-bubble-text/10 cursor-pointer"
        >
          Download
        </a>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-2 mt-1 text-[11px] text-theme-ai-bubble-text/60">
      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse shrink-0" />
      <span>Generating image ({job.status})…</span>
      {pollError && <span className="text-theme-ai-bubble-text/40">· retrying…</span>}
    </div>
  )
}
