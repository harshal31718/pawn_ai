import { useState, useEffect, useCallback } from 'react'
import {
  getKaggleConfig,
  setKaggleConfig,
  deleteKaggleConfig,
  connectKaggle,
  runGenerate,
  submitSessionJob,
  getJob,
  listJobs,
  IMAGE_JOB_POLL_INTERVAL_MS,
  type JobResult,
  type SessionStatus,
} from '../api/client'
import SessionBar from './SessionBar'
import GenerationsPanel from './GenerationsPanel'

interface Props {
  onClose: () => void
}

/**
 * A generative model exposed in the lab. Each one gets a tab in the
 * horizontal model bar and renders its own deploy + generate panel.
 * Add new models here to surface them as additional tabs.
 */
interface ModelDef {
  id: string
  /** Short label shown in the model tab bar. */
  title: string
  /** Heading shown above the generator panel. */
  heading: string
  /** Copy explaining what the deploy step pushes to Kaggle. */
  deployDescription: string
  /** Notebook slug pushed to Kaggle, surfaced in the GPU warning. */
  notebookSlug: string
  defaultPrompt: string
}

/**
 * Deploy is a one-time step per model (the notebook lives in the user's Kaggle
 * account afterwards), so we persist which models have been deployed and restore
 * it on load — otherwise Generate would be re-locked on every refresh until the
 * user pointlessly re-clicked Connect.
 */
const DEPLOYED_KEY = 'pawn-kaggle-deployed'

function loadDeployed(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(DEPLOYED_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

function saveDeployed(map: Record<string, boolean>) {
  try {
    localStorage.setItem(DEPLOYED_KEY, JSON.stringify(map))
  } catch {
    /* ignore quota / disabled storage */
  }
}

const MODELS: ModelDef[] = [
  {
    id: 'sdxl',
    title: 'SDXL',
    heading: 'SDXL Image Generator',
    deployDescription:
      'Connects to Kaggle and pushes the SDXL model runner notebook. This handles the model metadata and dataset mappings.',
    notebookSlug: 'pawn-image-sdxl',
    defaultPrompt: 'a cinematic shot of a highly detailed futuristic city',
  },
  {
    id: 'flux',
    title: 'FLUX.1-schnell',
    heading: 'FLUX.1-schnell Image Generator',
    deployDescription:
      'Connects to Kaggle and pushes the FLUX.1-schnell runner notebook (12B, bf16, sharded across 2× T4). Mounts the FLUX diffusers dataset on first generate.',
    notebookSlug: 'pawn-image-flux',
    defaultPrompt: 'a cinematic shot of a highly detailed futuristic city',
  },
]

export default function ImageLabPage({ onClose }: Props) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const [hasCreds, setHasCreds] = useState(false)
  const [activeModelId, setActiveModelId] = useState(MODELS[0].id)
  const [connected, setConnected] = useState<Record<string, boolean>>(loadDeployed)

  // Shared jobs list across all models for the unified Generations history.
  const [allJobs, setAllJobs] = useState<JobResult[]>([])
  const refreshAllJobs = useCallback(async () => {
    try {
      setAllJobs(await listJobs(undefined, 30))
    } catch { /* keep last */ }
  }, [])

  useEffect(() => {
    if (!hasCreds) return
    refreshAllJobs()
    const id = setInterval(refreshAllJobs, IMAGE_JOB_POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [hasCreds, refreshAllJobs])

  function markConnected(id: string, value: boolean) {
    setConnected((prev) => {
      const next = { ...prev, [id]: value }
      saveDeployed(next)
      return next
    })
  }

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden relative bg-theme-bg">
      {/* Floating Top Header */}
      <header className="absolute top-0 left-0 right-0 z-30 pointer-events-none p-4 flex items-center justify-between w-full">
        <div className="flex items-center gap-2 px-3.5 py-1.5 bg-theme-surface border border-theme-border/60 rounded-full shadow-md pointer-events-auto">
          <button
            type="button"
            onClick={onClose}
            className="px-0.5 py-0 rounded-full text-theme-text-muted hover:bg-theme-bg/50 hover:text-theme-text transition-colors focus:outline-none flex items-center justify-center"
            title="Back to chat"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
            </svg>
          </button>
          <h1 className="text-xs font-semibold text-theme-text select-none">Image Generation Lab</h1>
        </div>
      </header>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto pt-20 px-6 pb-10">
        <div className="max-w-md mx-auto space-y-5 py-4">

          {/* 1. Kaggle credentials bar */}
          <KaggleCredentials onChange={setHasCreds} />

          {hasCreds && (
            <>
              {/* 2. Model switch tabs */}
              <div className="flex items-center gap-1.5">
                {MODELS.map((m) => {
                  const active = m.id === activeModelId
                  return (
                    <button
                      key={m.id}
                      type="button"
                      onClick={() => setActiveModelId(m.id)}
                      className={`px-3.5 py-1.5 rounded-full text-xs font-semibold transition-colors cursor-pointer border ${
                        active
                          ? 'bg-theme-brand text-theme-brand-text border-transparent shadow-sm'
                          : 'bg-theme-surface text-theme-text-muted border-theme-border/60 hover:text-theme-text hover:bg-theme-surface-hover'
                      }`}
                    >
                      {m.title}
                      {connected[m.id] && (
                        <span className={`ml-1.5 inline-block w-1.5 h-1.5 rounded-full align-middle ${active ? 'bg-theme-brand-text/80' : 'bg-emerald-500'}`} />
                      )}
                    </button>
                  )
                })}
              </div>

              {/* Model panels — ALL rendered but only active one is visible.
                  Hidden panels stay mounted so SessionBar countdown + poll timers
                  survive tab switches without resetting. */}
              {MODELS.map((m) => (
                <div key={m.id} style={{ display: m.id === activeModelId ? undefined : 'none' }}>
                  <ModelPanel
                    model={m}
                    isConnected={!!connected[m.id]}
                    onConnected={() => markConnected(m.id, true)}
                    jobs={allJobs.filter((j) => j.model === m.id)}
                    onSubmitted={refreshAllJobs}
                  />
                </div>
              ))}

              {/* 3. Unified Generations history — all models */}
              <GenerationsPanel jobs={allJobs} />
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function ModelPanel({
  model,
  isConnected,
  onConnected,
  jobs,
  onSubmitted,
}: {
  model: ModelDef
  isConnected: boolean
  onConnected: () => void
  jobs: JobResult[]
  onSubmitted: () => void
}) {
  return (
    <div className="space-y-4">
      <KaggleConnector model={model} isConnected={isConnected} onConnected={onConnected} />
      <ImageGenerator
        model={model}
        isConnected={isConnected}
        jobs={jobs}
        onSubmitted={onSubmitted}
      />
    </div>
  )
}


/** Kaggle credentials setup — compact, collapses to a single row once saved. */
function KaggleCredentials({ onChange }: { onChange: (hasCreds: boolean) => void }) {
  const [username, setUsername] = useState('')
  const [apiToken, setApiToken] = useState('')
  const [hasCreds, setHasCreds] = useState(false)
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    getKaggleConfig()
      .then((s) => {
        if (active) {
          setHasCreds(s.has_creds)
          onChange(s.has_creds)
        }
      })
      .catch(() => {})
    return () => { active = false }
  }, [onChange])

  async function handleSave() {
    if (!username.trim() || !apiToken.trim()) {
      setError('Enter both your Kaggle username and API token.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await setKaggleConfig({ username: username.trim(), api_token: apiToken.trim() })
      setHasCreds(true)
      onChange(true)
      setApiToken('')
      setEditing(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleRemove() {
    setBusy(true)
    setError(null)
    try {
      await deleteKaggleConfig()
      saveDeployed({})  // creds gone → prior deploys no longer apply
      setHasCreds(false)
      onChange(false)
      setUsername('')
      setApiToken('')
      setEditing(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Remove failed')
    } finally {
      setBusy(false)
    }
  }

  // Collapsed: credentials saved and not being edited.
  if (hasCreds && !editing) {
    return (
      <div className="flex items-center justify-between gap-2 px-3 py-2 rounded-xl border border-theme-border/60 bg-theme-surface">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30 shrink-0">
            Saved
          </span>
          <span className="text-xs font-medium text-theme-text truncate">Kaggle Credentials</span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <button
            type="button"
            onClick={() => { setEditing(true); setError(null) }}
            disabled={busy}
            className="px-2.5 py-1 rounded-lg text-[11px] font-semibold text-theme-text border border-theme-border/60 hover:bg-theme-surface-hover disabled:opacity-60 cursor-pointer"
          >
            Edit
          </button>
          <button
            type="button"
            onClick={handleRemove}
            disabled={busy}
            className="px-2.5 py-1 rounded-lg text-[11px] font-semibold text-theme-text border border-theme-border/60 hover:bg-theme-surface-hover disabled:opacity-60 cursor-pointer"
          >
            {busy ? '...' : 'Remove'}
          </button>
        </div>
      </div>
    )
  }

  // Expanded: entering or editing credentials.
  return (
    <div className="p-3 rounded-xl border border-theme-border/60 bg-theme-surface space-y-2.5">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-semibold text-theme-text">Kaggle Credentials</h2>
        {hasCreds && (
          <button
            type="button"
            onClick={() => { setEditing(false); setError(null) }}
            className="text-[11px] font-semibold text-theme-text-muted hover:text-theme-text cursor-pointer"
          >
            Cancel
          </button>
        )}
      </div>

      <div className="space-y-2">
        <input
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          disabled={busy}
          placeholder="Kaggle username"
          className="w-full px-3 py-2 rounded-xl text-sm bg-theme-bg border border-theme-border/60 text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-border disabled:opacity-60"
        />
        <input
          type="password"
          value={apiToken}
          onChange={(e) => setApiToken(e.target.value)}
          disabled={busy}
          placeholder={hasCreds ? 'API token (saved — enter to replace)' : 'API token'}
          className="w-full px-3 py-2 rounded-xl text-sm bg-theme-bg border border-theme-border/60 text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-border disabled:opacity-60"
        />
      </div>

      <button
        type="button"
        onClick={handleSave}
        disabled={busy}
        className="px-4 py-2 rounded-xl text-xs font-semibold bg-theme-brand text-theme-brand-text shadow-sm hover:opacity-90 disabled:opacity-60 cursor-pointer"
      >
        {busy ? 'Saving...' : 'Save Credentials'}
      </button>

      {error && <div className="text-xs text-red-600 dark:text-red-400">{error}</div>}
    </div>
  )
}

/** Deploys the worker instance notebook first-time to user's Kaggle */
function KaggleConnector({
  model,
  isConnected,
  onConnected,
}: {
  model: ModelDef
  isConnected: boolean
  onConnected: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleConnect() {
    setBusy(true)
    setError(null)
    try {
      await connectKaggle(model.id)
      onConnected()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Connection/deploy failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="p-4 rounded-xl border border-theme-border/60 bg-theme-surface space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-semibold text-theme-text">Connection & Notebook Deployment</h2>
        {isConnected && (
          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30">
            Deployed
          </span>
        )}
      </div>
      <p className="text-xs text-theme-text-muted">{model.deployDescription}</p>
      {isConnected && (
        <p className="text-[10px] text-amber-600 dark:text-amber-400 bg-amber-500/10 p-2.5 rounded-xl leading-relaxed">
          <strong>Important:</strong> If Kaggle runs fail on a P100 GPU (e.g. CUDA kernel mismatch), please open the pushed notebook <strong>{model.notebookSlug}</strong> on kaggle.com and change the Accelerator to <strong>GPU T4</strong> in the Settings panel.
        </p>
      )}
      <button
        type="button"
        onClick={handleConnect}
        disabled={busy}
        className="px-4 py-2 rounded-xl text-xs font-semibold bg-theme-brand text-theme-brand-text shadow-sm hover:opacity-90 disabled:opacity-60 cursor-pointer"
      >
        {busy ? 'Deploying to Kaggle...' : isConnected ? 'Re-deploy Notebook' : 'Connect to Kaggle'}
      </button>
      {error && <div className="text-xs text-red-600 dark:text-red-400">{error}</div>}
    </div>
  )
}

/**
 * Job-driven generator (Phase W.2). Submission returns a durable job id; the
 * button's busy state is DERIVED FROM THE SERVER jobs list (disabled while this
 * model has a queued/running job), so a refresh or second tab can't fire a
 * duplicate run. A warm session routes Generate to the live kernel (fast); with
 * no session it runs a single cold image. Results also persist in the panel below.
 */
function ImageGenerator({
  model,
  isConnected,
  jobs,
  onSubmitted,
}: {
  model: ModelDef
  isConnected: boolean
  jobs: JobResult[]
  onSubmitted: () => void
}) {
  const [prompt, setPrompt] = useState('')
  const [session, setSession] = useState<SessionStatus | null>(null)
  // Set of job IDs submitted this session — watched for inline result display.
  // The server-backed GenerationsPanel is the source of truth; this just drives
  // the inline "last completed" preview above the panel.
  const [watchIds, setWatchIds] = useState<Set<string>>(new Set())
  const [submitting, setSubmitting] = useState(false)
  const [latestResult, setLatestResult] = useState<JobResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Clear local state when model changes (panel stays mounted, model prop changes).
  useEffect(() => {
    setPrompt('')
    setLatestResult(null)
    setError(null)
    setWatchIds(new Set())
  }, [model.id])

  const live = !!session?.alive
  // A session is "warm-routable" if it exists and has a session_id — even during
  // warmup phases (installing / loading_model). Jobs queued now will sit in
  // Supabase and the kernel picks them up the moment it enters its serve loop.
  const hasSession = !!session?.session_id

  // Poll all submitted job IDs until each resolves; update inline preview with
  // the most recently completed one. GenerationsPanel handles the full history.
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
              // Don't settle immediately if the session is still alive/warming —
              // the kernel may have been mid-inference when reap ran and will write
              // 'done' shortly after. Keep polling until the session is confirmed dead.
              const sessionAlive = !!session && (session.alive || hasSession)
              if (!sessionAlive) {
                settled.add(jid)
                setLatestResult((prev) => prev ?? job)
              }
              // If session is still alive, keep polling — kernel may overwrite error→done.
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

  // Cold path: one Kaggle container per model — block while one is active.
  // Warm/warmup path: kernel queues jobs; allow unlimited queuing, only block
  // the button during the actual HTTP submit (prevents true double-clicks).
  const coldJobActive = !hasSession && jobs.some(
    (j) => j.status === 'queued' || j.status === 'running',
  )
  const busy = coldJobActive || submitting

  // Jobs waiting to be picked up by the warm kernel.
  const queuedCount = jobs.filter((j) => j.status === 'queued').length
  const runningCount = jobs.filter((j) => j.status === 'running').length

  async function handleGenerate() {
    if (!prompt.trim()) {
      setError('Enter a prompt.')
      return
    }
    if (busy) return
    setError(null)
    setSubmitting(true)
    try {
      const { job_id } =
        hasSession && session?.session_id
          ? await submitSessionJob(session.session_id, prompt.trim())
          : await runGenerate(model.id, prompt.trim())
      setWatchIds((prev) => new Set([...prev, job_id]))
      setPrompt('') // clear immediately so user can type the next prompt
      onSubmitted()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Generation failed')
    } finally {
      setSubmitting(false)
    }
  }

  const resultIsImage = !!latestResult && (latestResult.mime ?? '').startsWith('image/')

  return (
    <div className="p-4 rounded-xl border border-theme-border/60 bg-theme-surface space-y-3">
      <h2 className="text-xs font-semibold text-theme-text">{model.heading}</h2>

      {isConnected && <SessionBar model={model.id} onSession={setSession} />}

      <div className="space-y-2">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          disabled={!isConnected || busy}
          placeholder="Describe the image you want to generate..."
          className="w-full h-20 px-3 py-2 rounded-xl text-sm bg-theme-bg border border-theme-border/60 text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-border disabled:opacity-60 resize-none"
        />
        <button
          type="button"
          onClick={handleGenerate}
          disabled={!isConnected || busy}
          className="w-full py-2.5 rounded-xl text-xs font-semibold bg-theme-brand text-theme-brand-text shadow-sm hover:opacity-90 disabled:opacity-60 cursor-pointer"
        >
          {submitting
            ? 'Queuing…'
            : live
              ? 'Generate (warm · queue)'
              : coldJobActive
                ? 'Generating (cold ~14 min)…'
                : 'Generate once (cold ~14 min)'}
        </button>
        {/* Queue status — only shown during warm sessions */}
        {live && (queuedCount > 0 || runningCount > 0) && (
          <div className="flex items-center gap-1.5 text-[11px] text-theme-text-muted">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse shrink-0" />
            {runningCount > 0 && <span>Generating 1 image…</span>}
            {queuedCount > 0 && (
              <span className="text-theme-text-muted/70">
                {runningCount > 0 ? `· ` : ''}{queuedCount} more queued
              </span>
            )}
          </div>
        )}
      </div>

      {!isConnected && (
        <div className="text-[10px] text-amber-600 dark:text-amber-400">
          Please connect to Kaggle and deploy the worker notebook above first.
        </div>
      )}

      {/* Inline preview of the most recently completed image */}
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
  )
}
