import { useState, useEffect, useRef } from 'react'
import {
  runKaggleCube,
  getKaggleConfig,
  setKaggleConfig,
  deleteKaggleConfig,
  type CubeResult,
} from '../api/client'

interface Props {
  onClose: () => void
}

/**
 * Milestone A.0 — throwaway "Kaggle Lab" page that proves the Kaggle round-trip
 * with a trivial findCube(int) before any image model. Opens in place of the
 * chat area, mirroring SettingsPage. Credentials live here for now (NOT in
 * Settings). Deletable in one commit (this file + its sidebar button + wiring).
 */
export default function ImageLabPage({ onClose }: Props) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const [hasCreds, setHasCreds] = useState(false)

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
          <h1 className="text-xs font-semibold text-theme-text select-none">Kaggle Lab</h1>
        </div>
      </header>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto pt-20 px-6 pb-10">
        <div className="max-w-md mx-auto space-y-8 py-4">
          <KaggleCredentials onChange={setHasCreds} />
          <CubeRunner hasCreds={hasCreds} />
        </div>
      </div>
    </div>
  )
}

/** Kaggle username + API token entry. Token is write-only (never returned). */
function KaggleCredentials({ onChange }: { onChange: (hasCreds: boolean) => void }) {
  const [username, setUsername] = useState('')
  const [apiToken, setApiToken] = useState('')
  const [hasCreds, setHasCreds] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    let active = true
    getKaggleConfig()
      .then((s) => { if (active) { setHasCreds(s.has_creds); onChange(s.has_creds) } })
      .catch(() => { /* backend not ready / no creds — treat as unconfigured */ })
    return () => { active = false }
  }, [onChange])

  async function handleSave() {
    if (!username.trim() || !apiToken.trim()) {
      setError('Enter both your Kaggle username and API token.')
      return
    }
    setBusy(true)
    setError(null)
    setSaved(false)
    try {
      await setKaggleConfig({ username: username.trim(), api_token: apiToken.trim() })
      setHasCreds(true)
      onChange(true)
      setApiToken('')
      setSaved(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleRemove() {
    setBusy(true)
    setError(null)
    setSaved(false)
    try {
      await deleteKaggleConfig()
      setHasCreds(false)
      onChange(false)
      setUsername('')
      setApiToken('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Remove failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-[10px] font-semibold uppercase tracking-widest text-theme-text-muted">
          Kaggle credentials
        </h2>
        {hasCreds && (
          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30">
            Configured
          </span>
        )}
      </div>

      <p className="text-xs text-theme-text-muted leading-relaxed">
        Used to run notebooks in your own Kaggle account. Requires a phone-verified Kaggle
        account (needed for free GPU + internet). Your token is encrypted and never shown again.
      </p>

      <div className="space-y-2">
        <input
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          disabled={busy}
          autoComplete="off"
          placeholder="Kaggle username"
          className="w-full px-3 py-2 rounded-xl text-sm bg-theme-surface border border-theme-border/60 text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-border disabled:opacity-60"
        />
        <input
          type="password"
          value={apiToken}
          onChange={(e) => setApiToken(e.target.value)}
          disabled={busy}
          autoComplete="off"
          placeholder={hasCreds ? 'API token (saved — enter to replace)' : 'API token'}
          className="w-full px-3 py-2 rounded-xl text-sm bg-theme-surface border border-theme-border/60 text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-border disabled:opacity-60"
        />
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={handleSave}
          disabled={busy}
          className="px-4 py-2 rounded-xl text-xs font-semibold bg-theme-brand text-theme-brand-text shadow-sm hover:opacity-90 transition-all active:scale-98 cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {busy ? 'Saving…' : 'Save'}
        </button>
        {hasCreds && (
          <button
            type="button"
            onClick={handleRemove}
            disabled={busy}
            className="px-3 py-2 rounded-xl text-xs font-semibold text-theme-text border border-theme-border/60 hover:bg-theme-surface-hover transition-all active:scale-98 cursor-pointer disabled:opacity-60"
          >
            Remove
          </button>
        )}
        {saved && !busy && <span className="text-[10px] text-emerald-600 dark:text-emerald-400">Saved</span>}
      </div>

      {error && (
        <div className="text-xs text-red-600 dark:text-red-400 break-words whitespace-pre-wrap">{error}</div>
      )}
    </div>
  )
}

/** Sends an integer to the Kaggle findCube kernel and shows the cube. */
function CubeRunner({ hasCreds }: { hasCreds: boolean }) {
  const [value, setValue] = useState('5')
  const [status, setStatus] = useState<'idle' | 'running'>('idle')
  const [result, setResult] = useState<CubeResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [elapsedMs, setElapsedMs] = useState<number | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  // Abort any in-flight request if the page unmounts.
  useEffect(() => () => abortRef.current?.abort(), [])

  async function handleRun() {
    const n = Number(value)
    if (value.trim() === '' || !Number.isInteger(n)) {
      setError('Enter a whole number.')
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
      const res = await runKaggleCube(n, ctrl.signal)
      setResult(res)
      setElapsedMs(Date.now() - startedAt)
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      setError(err instanceof Error ? err.message : 'Run failed')
      setElapsedMs(Date.now() - startedAt)
    } finally {
      setStatus('idle')
    }
  }

  const running = status === 'running'

  return (
    <div className="space-y-3">
      <div>
        <h2 className="text-[10px] font-semibold uppercase tracking-widest text-theme-text-muted mb-1">
          Round-trip proof — findCube
        </h2>
        <p className="text-xs text-theme-text-muted leading-relaxed">
          Sends an integer to your Kaggle notebook, which returns its cube. Proves the
          deploy → run → poll → output transport before any image model.
        </p>
      </div>

      <div className="flex items-end gap-2">
        <div className="flex-1">
          <label className="block text-[10px] font-semibold uppercase tracking-widest text-theme-text-muted mb-1.5">
            Integer
          </label>
          <input
            type="number"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !running) handleRun() }}
            disabled={running}
            className="w-full px-3 py-2 rounded-xl text-sm bg-theme-surface border border-theme-border/60 text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-border disabled:opacity-60"
            placeholder="e.g. 5"
          />
        </div>
        <button
          type="button"
          onClick={handleRun}
          disabled={running}
          className="px-4 py-2 rounded-xl text-xs font-semibold bg-theme-brand text-theme-brand-text shadow-sm hover:opacity-90 transition-all active:scale-98 cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {running ? 'Running…' : 'Run'}
        </button>
      </div>

      {!hasCreds && (
        <div className="text-[10px] text-amber-600 dark:text-amber-400">
          Add your Kaggle credentials above first.
        </div>
      )}

      {running && (
        <div className="flex items-center gap-2 text-xs text-theme-text-muted">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse shrink-0" />
          <span>Queued → running on Kaggle…</span>
        </div>
      )}

      {result && !running && (
        <div className="rounded-xl border border-theme-border/60 bg-theme-surface px-4 py-3">
          <div className="text-2xl font-semibold text-theme-text tabular-nums">
            {result.input} <span className="text-theme-text-muted">→</span> {result.result}
          </div>
          <div className="mt-1 text-[10px] text-theme-text-muted">
            {result.via ? `via ${result.via}` : 'returned from Kaggle'}
            {elapsedMs != null && ` · ${(elapsedMs / 1000).toFixed(1)}s`}
          </div>
        </div>
      )}

      {error && !running && (
        <div className="rounded-xl border border-red-300 dark:border-red-700/60 bg-red-50 dark:bg-red-900/20 px-4 py-3">
          <div className="text-xs font-semibold text-red-700 dark:text-red-300 mb-0.5">Failed</div>
          <div className="text-xs text-red-700/90 dark:text-red-300/90 break-words whitespace-pre-wrap">{error}</div>
          {elapsedMs != null && (
            <div className="mt-1 text-[10px] text-red-700/70 dark:text-red-300/70">
              after {(elapsedMs / 1000).toFixed(1)}s
            </div>
          )}
        </div>
      )}
    </div>
  )
}
