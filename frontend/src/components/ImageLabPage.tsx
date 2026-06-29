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
  // Deploy state is tracked per model so each tab remembers its own status, and
  // persisted so a one-time deploy keeps Generate clickable across reloads.
  const [connected, setConnected] = useState<Record<string, boolean>>(loadDeployed)

  // Shared, server-backed jobs list (all models) — the single source of truth for
  // the Generations monitor AND for server-derived button state (a model with an
  // active job can't be re-submitted, and this survives a refresh).
  const [jobs, setJobs] = useState<JobResult[]>([])
  const refreshJobs = useCallback(async () => {
    try {
      setJobs(await listJobs(undefined, 30))
    } catch {
      /* transient — keep the last list */
    }
  }, [])

  useEffect(() => {
    if (!hasCreds) return
    refreshJobs()
    const id = setInterval(refreshJobs, IMAGE_JOB_POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [hasCreds, refreshJobs])

  const activeModel = MODELS.find((m) => m.id === activeModelId) ?? MODELS[0]
  const isConnected = !!connected[activeModel.id]

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
          <KaggleCredentials onChange={setHasCreds} />

          {hasCreds && (
            <>
              {/* Horizontal model bar — each title is a button for its panel */}
              <div className="flex items-center gap-1.5 overflow-x-auto -mx-1 px-1 pb-0.5">
                {MODELS.map((m) => {
                  const active = m.id === activeModel.id
                  return (
                    <button
                      key={m.id}
                      type="button"
                      onClick={() => setActiveModelId(m.id)}
                      className={`shrink-0 px-3.5 py-1.5 rounded-full text-xs font-semibold transition-colors cursor-pointer border ${
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

              {/* Active model panel — deploy + generate. Keyed by model id so each
                  model gets its OWN component instance: a running generate on one
                  model can't leak its busy state into another and disable it. */}
              <div className="space-y-5">
                <KaggleConnector
                  key={`connect-${activeModel.id}`}
                  model={activeModel}
                  isConnected={isConnected}
                  onConnected={() => markConnected(activeModel.id, true)}
                />
                <ImageGenerator
                  key={`gen-${activeModel.id}`}
                  model={activeModel}
                  isConnected={isConnected}
                  jobs={jobs}
                  onSubmitted={refreshJobs}
                />
                <GenerationsPanel jobs={jobs} />
              </div>
            </>
          )}
        </div>
      </div>
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
  const [prompt, setPrompt] = useState(model.defaultPrompt)
  const [session, setSession] = useState<SessionStatus | null>(null)
  const [watchId, setWatchId] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<JobResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Reset generator state when switching models.
  useEffect(() => {
    setPrompt(model.defaultPrompt)
    setResult(null)
    setError(null)
    setWatchId(null)
  }, [model.id, model.defaultPrompt])

  // Poll the job we just submitted so we can render it inline. (After a refresh
  // this local watch is lost, but the job still shows in the panel — server-backed.)
  useEffect(() => {
    if (!watchId) return
    let active = true
    const id = setInterval(async () => {
      try {
        const job = await getJob(watchId)
        if (!active) return
        if (job.status === 'done' || job.status === 'error') {
          setResult(job)
          setWatchId(null)
          onSubmitted()
        }
      } catch {
        /* keep polling */
      }
    }, IMAGE_JOB_POLL_INTERVAL_MS)
    return () => {
      active = false
      clearInterval(id)
    }
  }, [watchId, onSubmitted])

  const live = !!session?.alive
  // Server-derived: an in-flight job for this model (cold or warm) blocks new
  // submits and survives a refresh. `submitting` closes the local window between
  // the click and the server response (before activeJob/watchId are known) so a
  // fast double-click can't fire two runs.
  const activeJob = jobs.find(
    (j) => j.model === model.id && (j.status === 'queued' || j.status === 'running'),
  )
  const busy = !!activeJob || !!watchId || submitting

  async function handleGenerate() {
    if (!prompt.trim()) {
      setError('Enter a prompt.')
      return
    }
    if (busy) return
    setError(null)
    setResult(null)
    setSubmitting(true)
    try {
      const { job_id } =
        live && session?.session_id
          ? await submitSessionJob(session.session_id, prompt.trim())
          : await runGenerate(model.id, prompt.trim())
      setWatchId(job_id)
      onSubmitted() // refresh shared jobs → button stays disabled, panel shows it
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Generation failed')
    } finally {
      setSubmitting(false)
    }
  }

  const resultIsImage = !!result && (result.mime ?? '').startsWith('image/')

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
          {busy
            ? live
              ? 'Generating (warm)…'
              : 'Generating (cold ~14 min)…'
            : live
              ? 'Generate (warm · seconds)'
              : 'Generate once (cold ~14 min)'}
        </button>
      </div>

      {!isConnected && (
        <div className="text-[10px] text-amber-600 dark:text-amber-400">
          Please connect to Kaggle and deploy the worker notebook above first.
        </div>
      )}

      {busy && (
        <div className="flex items-center gap-2 text-xs text-theme-text-muted">
          <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse shrink-0" />
          <span>
            {live
              ? 'Generating on the warm kernel…'
              : 'Running a fresh Kaggle container (cold start). Track it in Generations below.'}
          </span>
        </div>
      )}

      {result && result.status === 'done' && resultIsImage && result.image_b64 && (
        <div className="space-y-2">
          <div className="rounded-xl overflow-hidden border border-theme-border/60 bg-theme-bg flex justify-center">
            <img
              src={`data:${result.mime};base64,${result.image_b64}`}
              alt={result.prompt ?? prompt}
              className="max-w-full h-auto object-contain max-h-[300px]"
            />
          </div>
          <div className="text-[10px] text-theme-text-muted">
            {result.via ? `via ${result.via}` : 'returned from Kaggle'}
          </div>
        </div>
      )}

      {result && result.status === 'done' && !resultIsImage && (
        <div className="p-2 rounded-lg bg-theme-bg border border-theme-border/60 text-theme-text text-xs break-words">
          {(() => {
            try {
              return result.image_b64 ? atob(result.image_b64) : ''
            } catch {
              return result.image_b64 ?? ''
            }
          })()}
        </div>
      )}

      {((result && result.status === 'error') || error) && (
        <div className="p-3 rounded-xl border border-red-200 dark:border-red-900/50 bg-red-50 dark:bg-red-950/20 text-xs text-red-800 dark:text-red-300 font-medium break-words">
          {error ?? result?.error ?? 'Generation failed'}
        </div>
      )}
    </div>
  )
}
