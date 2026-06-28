import { useState, useEffect, useRef } from 'react'
import {
  getKaggleConfig,
  setKaggleConfig,
  deleteKaggleConfig,
  connectKaggle,
  runKaggleImage,
  type ImageResult,
} from '../api/client'

interface Props {
  onClose: () => void
}

export default function ImageLabPage({ onClose }: Props) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const [hasCreds, setHasCreds] = useState(false)
  const [isConnected, setIsConnected] = useState(false)

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
        <div className="max-w-md mx-auto space-y-8 py-4">
          <KaggleCredentials onChange={setHasCreds} onConnectChange={setIsConnected} />
          {hasCreds && (
            <>
              <KaggleConnector isConnected={isConnected} onConnected={() => setIsConnected(true)} />
              <ImageGenerator isConnected={isConnected} />
            </>
          )}
        </div>
      </div>
    </div>
  )
}

/** Kaggle credentials setup */
function KaggleCredentials({
  onChange,
  onConnectChange,
}: {
  onChange: (hasCreds: boolean) => void
  onConnectChange: (connected: boolean) => void
}) {
  const [username, setUsername] = useState('')
  const [apiToken, setApiToken] = useState('')
  const [hasCreds, setHasCreds] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    getKaggleConfig()
      .then((s) => {
        if (active) {
          setHasCreds(s.has_creds)
          onChange(s.has_creds)
          // If we had config, assume we might need to connect first
          onConnectChange(false)
        }
      })
      .catch(() => {})
    return () => { active = false }
  }, [onChange, onConnectChange])

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
      onConnectChange(false)
      setApiToken('')
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
      setHasCreds(false)
      onChange(false)
      onConnectChange(false)
      setUsername('')
      setApiToken('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Remove failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="p-4 rounded-xl border border-theme-border/60 bg-theme-surface space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-semibold text-theme-text">1. Kaggle Credentials</h2>
        {hasCreds && (
          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30">
            Saved
          </span>
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

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={handleSave}
          disabled={busy}
          className="px-4 py-2 rounded-xl text-xs font-semibold bg-theme-brand text-theme-brand-text shadow-sm hover:opacity-90 disabled:opacity-60 cursor-pointer"
        >
          {busy ? 'Saving...' : 'Save Credentials'}
        </button>
        {hasCreds && (
          <button
            type="button"
            onClick={handleRemove}
            disabled={busy}
            className="px-3 py-2 rounded-xl text-xs font-semibold text-theme-text border border-theme-border/60 hover:bg-theme-surface-hover disabled:opacity-60 cursor-pointer"
          >
            Remove
          </button>
        )}
      </div>

      {error && <div className="text-xs text-red-600 dark:text-red-400">{error}</div>}
    </div>
  )
}

/** Deploys the worker instance notebook first-time to user's Kaggle */
function KaggleConnector({
  isConnected,
  onConnected,
}: {
  isConnected: boolean
  onConnected: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleConnect() {
    setBusy(true)
    setError(null)
    try {
      await connectKaggle()
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
        <h2 className="text-xs font-semibold text-theme-text">2. Connection & Notebook Deployment</h2>
        {isConnected && (
          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30">
            Deployed
          </span>
        )}
      </div>
      <p className="text-xs text-theme-text-muted">
        Connects to Kaggle and pushes the SDXL model runner notebook. This handles the model metadata and dataset mappings.
      </p>
      {isConnected && (
        <p className="text-[10px] text-amber-600 dark:text-amber-400 bg-amber-500/10 p-2.5 rounded-xl leading-relaxed">
          <strong>Important:</strong> If Kaggle runs fail on a P100 GPU (e.g. CUDA kernel mismatch), please open the pushed notebook <strong>pawn-image-poc</strong> on kaggle.com and change the Accelerator to <strong>GPU T4</strong> in the Settings panel.
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

/** Generates image from user text prompts */
function ImageGenerator({ isConnected }: { isConnected: boolean }) {
  const [prompt, setPrompt] = useState('a cinematic shot of a highly detailed futuristic city')
  const [status, setStatus] = useState<'idle' | 'running'>('idle')
  const [result, setResult] = useState<ImageResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [elapsedMs, setElapsedMs] = useState<number | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => () => abortRef.current?.abort(), [])

  async function handleGenerate() {
    if (!prompt.trim()) {
      setError('Enter a prompt.')
      return
    }
    setStatus('running')
    setError(null)
    setResult(null)
    setElapsedMs(null)
    const startedAt = Date.now()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      const res = await runKaggleImage(prompt.trim(), ctrl.signal)
      setResult(res)
      setElapsedMs(Date.now() - startedAt)
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      setError(err instanceof Error ? err.message : 'Generation failed')
      setElapsedMs(Date.now() - startedAt)
    } finally {
      setStatus('idle')
    }
  }

  const running = status === 'running'

  return (
    <div className="p-4 rounded-xl border border-theme-border/60 bg-theme-surface space-y-4">
      <h2 className="text-xs font-semibold text-theme-text">3. SDXL Image Generator</h2>
      
      <div className="space-y-2">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          disabled={!isConnected || running}
          placeholder="Describe the image you want to generate..."
          className="w-full h-20 px-3 py-2 rounded-xl text-sm bg-theme-bg border border-theme-border/60 text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-border disabled:opacity-60 resize-none"
        />
        <button
          type="button"
          onClick={handleGenerate}
          disabled={!isConnected || running}
          className="w-full py-2.5 rounded-xl text-xs font-semibold bg-theme-brand text-theme-brand-text shadow-sm hover:opacity-90 disabled:opacity-60 cursor-pointer"
        >
          {running ? 'Generating (takes ~1-2 min)...' : 'Generate Image'}
        </button>
      </div>

      {!isConnected && (
        <div className="text-[10px] text-amber-600 dark:text-amber-400">
          Please connect to Kaggle and deploy the worker notebook above first.
        </div>
      )}

      {running && (
        <div className="flex items-center gap-2 text-xs text-theme-text-muted">
          <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse shrink-0" />
          <span>Notebook running on Kaggle GPU (waits for warmup if just deployed). Awaiting output...</span>
        </div>
      )}

      {result && !running && (
        <div className="space-y-2">
          <div className="rounded-xl overflow-hidden border border-theme-border/60 bg-theme-bg flex justify-center">
            <img
              src={`data:${result.mime};base64,${result.image}`}
              alt={prompt}
              className="max-w-full h-auto object-contain max-h-[300px]"
            />
          </div>
          <div className="text-[10px] text-theme-text-muted">
            {result.via ? `via ${result.via}` : 'returned from Kaggle'}
            {elapsedMs != null && ` · ${(elapsedMs / 1000).toFixed(1)}s`}
          </div>
        </div>
      )}

      {error && !running && (
        <div className="p-3 rounded-xl border border-red-200 dark:border-red-900/50 bg-red-50 dark:bg-red-950/20 text-xs text-red-800 dark:text-red-300 font-medium break-words">
          {error}
          {elapsedMs != null && (
            <div className="mt-1 text-[10px] opacity-70">after {(elapsedMs / 1000).toFixed(1)}s</div>
          )}
        </div>
      )}
    </div>
  )
}
