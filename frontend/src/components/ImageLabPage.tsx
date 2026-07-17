import { useState, useEffect, useCallback, useRef } from 'react'
import {
  connectKaggle,
  listJobs,
  IMAGE_JOB_POLL_INTERVAL_MS,
  type JobResult,
  type SessionStatus,
} from '../api/client'
import GenerationsPanel from './GenerationsPanel'
import KaggleCredentials from './KaggleCredentials'
import ImageGenerator, { type ModelDef, WARMUP_STATUSES } from './ImageGenerator'
import { loadDeployed, saveDeployed } from '../store/deployedStore'
import type { RefineHandler, ReuseSeedHandler, EditHandler } from '../types'

interface Props {
  onClose: () => void
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
  const [deployingModelId, setDeployingModelId] = useState<string | null>(null)
  const [deployError, setDeployError] = useState<string | null>(null)
  const [sessions, setSessions] = useState<Record<string, SessionStatus | null>>({})
  const [sessionBusy, setSessionBusy] = useState<Record<string, 'start' | 'stop' | 'extend' | null>>({})

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

  async function handleRedeployAll() {
    setDeployingModelId('all')
    setDeployError(null)
    try {
      await Promise.all(MODELS.map((m) => connectKaggle(m.id)))
      MODELS.forEach((m) => markConnected(m.id, true))
    } catch (err) {
      setDeployError(err instanceof Error ? err.message : 'Redeploy all failed')
    } finally {
      setDeployingModelId(null)
    }
  }

  const generatorRef = useRef<{ triggerRefine: RefineHandler; triggerReuseSeed: ReuseSeedHandler; triggerEdit: EditHandler } | null>(null)
  const handleRefine: RefineHandler = useCallback((job, imageSrc) => {
    generatorRef.current?.triggerRefine(job, imageSrc)
  }, [])
  const handleReuseSeed: ReuseSeedHandler = useCallback((seed) => {
    generatorRef.current?.triggerReuseSeed(seed)
  }, [])
  const handleEdit: EditHandler = useCallback((job) => {
    generatorRef.current?.triggerEdit(job)
  }, [])

  const activeModelJobs = allJobs.filter((j) => j.model === activeModelId)

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden relative bg-theme-bg pt-16">
      {/* Floating Top Header */}
      <header className="absolute top-0 left-0 right-0 z-30 pointer-events-none p-4 flex items-center justify-between w-full">
        <div className="flex items-center gap-2 h-7 pl-2 pr-3 bg-theme-surface border border-theme-border/60 rounded-xl shadow-md pointer-events-auto z-20 transition-all">
          <button
            type="button"
            onClick={onClose}
            className="rounded-full text-theme-text-muted hover:bg-theme-bg/50 hover:text-theme-text transition-colors focus:outline-none flex items-center justify-center cursor-pointer"
            title="Back to chat"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
            </svg>
          </button>
          <h1 className="text-xs font-semibold text-theme-text select-none">Image Generation Lab</h1>
        </div>
      </header>

      {/* Row 1: Model tabs + Kaggle credentials */}
      <div className="px-4 pb-2.5 border-b border-theme-border/40 flex items-center justify-between">
        {/* Model selection tabs */}
        <div className="py-1 px-2 rounded-xl border border-theme-border/60 bg-theme-surface flex items-center gap-3 shadow-sm">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-theme-text select-none">Model</h2>
          <div className="flex items-center gap-1">
            {MODELS.map((m) => {
              const active = m.id === activeModelId
              const sStatus = sessions[m.id]?.status || 'none'
              const sBusy = sessionBusy[m.id]
              const isStopping = sStatus === 'stopping' || sBusy === 'stop'
              const isRunning = sStatus === 'ready' && !isStopping
              const isWarming = WARMUP_STATUSES.has(sStatus) && !isStopping
              const isCurrentlyDeploying = deployingModelId === m.id || deployingModelId === 'all'

              const colorCls = active
                ? isRunning
                  ? 'bg-emerald-600 dark:bg-emerald-500 text-white dark:text-zinc-950 border-transparent shadow-sm'
                  : isWarming
                    ? 'bg-amber-500 dark:bg-amber-400 text-zinc-950 dark:text-zinc-950 border-transparent shadow-sm'
                    : isStopping
                      ? 'bg-red-600 dark:bg-red-500 text-white dark:text-zinc-950 border-transparent shadow-sm'
                      : 'bg-white dark:bg-zinc-100 text-zinc-950 dark:text-zinc-950 border-transparent shadow-sm'
                : isRunning
                  ? 'bg-emerald-500/5 border-emerald-500/15 text-emerald-600/70 dark:text-emerald-400/70 hover:bg-emerald-500/10 hover:text-emerald-600 dark:hover:text-emerald-400'
                  : isWarming
                    ? 'bg-amber-500/5 border-amber-500/15 text-amber-600/70 dark:text-amber-400/70 hover:bg-amber-500/10 hover:text-amber-600 dark:hover:text-amber-400'
                    : isStopping
                      ? 'bg-red-500/5 border-red-500/15 text-red-600/70 dark:text-red-400/70 hover:bg-red-500/10 hover:text-red-600 dark:hover:text-red-400'
                      : 'bg-white/5 border-zinc-200/10 dark:border-zinc-800/10 text-theme-text-muted hover:bg-white/10 hover:text-theme-text'

              return (
                <div
                  key={m.id}
                  onClick={() => { if (!isCurrentlyDeploying) setActiveModelId(m.id) }}
                  className={`px-3 py-1 rounded-full text-xs font-semibold border flex items-center gap-2 cursor-pointer transition-all ${colorCls}`}
                >
                  {isCurrentlyDeploying ? (
                    <div className="flex items-center gap-1.5 select-none">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-ping shrink-0" />
                      <span className="animate-pulse">Deploying…</span>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1.5 select-none">
                      <span>{m.title}</span>
                      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${active
                        ? 'bg-current'
                        : isRunning
                          ? 'bg-emerald-500 animate-pulse'
                          : isWarming
                            ? 'bg-amber-500 animate-pulse'
                            : isStopping
                              ? 'bg-red-500 animate-pulse'
                              : 'bg-zinc-400 dark:bg-zinc-500'}`} />
                      <span className="text-[10px] font-medium opacity-90">
                        {isRunning ? 'Running' : isWarming ? 'Warming' : isStopping ? 'Stopping' : 'Idle'}
                      </span>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* Kaggle credentials */}
        <div className="flex justify-end shrink-0">
          <KaggleCredentials
            hasCreds={hasCreds}
            onChange={setHasCreds}
            onRedeployAll={handleRedeployAll}
            isRedeploying={deployingModelId === 'all'}
          />
        </div>
      </div>

      {deployError && (
        <div className="mx-5 mt-2.5 p-2.5 rounded-xl bg-red-500/10 border border-red-500/20 text-red-600 dark:text-red-400 text-xs font-semibold flex items-center justify-between">
          <span>Deployment failed: {deployError}</span>
          <button onClick={() => setDeployError(null)} className="text-red-600 dark:text-red-400 hover:text-red-700 font-bold uppercase text-[10px] cursor-pointer">Dismiss</button>
        </div>
      )}

      {/* Row 2: Two-column layout */}
      <div className="flex-1 flex overflow-hidden">

        {/* LEFT COLUMN: generator controls */}
        <div className="w-[480px] min-w-[420px] shrink-0 border-r border-theme-border/40 flex flex-col overflow-hidden">
          <div className="flex-1 flex flex-col overflow-hidden px-3.5 pt-0 pb-0">
            {hasCreds && (
              <>
                {/* All models stay mounted — only visibility changes via display:none */}
                {MODELS.map((m) => (
                  <div
                    key={`gen-${m.id}`}
                    style={{ display: m.id === activeModelId ? 'flex' : 'none' }}
                    className="flex-col flex-1 h-full overflow-hidden"
                  >
                    <ImageGenerator
                      ref={m.id === activeModelId ? generatorRef : undefined}
                      model={m}
                      jobs={allJobs.filter((j) => j.model === m.id)}
                      isConnected={!!connected[m.id]}
                      onSubmitted={refreshAllJobs}
                      session={sessions[m.id] ?? null}
                      setSession={(s) => setSessions((prev) => ({ ...prev, [m.id]: s }))}
                      busyAction={sessionBusy[m.id] ?? null}
                      setBusyAction={(action) => setSessionBusy((prev) => ({ ...prev, [m.id]: action }))}
                    />
                  </div>
                ))}
              </>
            )}
          </div>
        </div>

        {/* RIGHT COLUMN: generations history */}
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden pr-4 pb-0">
          <GenerationsPanel
            jobs={activeModelJobs}
            onRefine={handleRefine}
            onReuseSeed={handleReuseSeed}
            onEdit={handleEdit}
            onJobsChanged={refreshAllJobs}
          />
        </div>

      </div>
    </div>
  )
}
