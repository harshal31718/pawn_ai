import { useEffect, useState, type ReactNode } from 'react'
import {
  getKeys,
  setKey as apiSetKey,
  deleteKey as apiDeleteKey,
  getKaggleConfig,
  setKaggleConfig,
  deleteKaggleConfig,
  getDriveStatus,
} from '../api/client'
import { useAuth } from '../contexts/AuthContext'

// Mirrors backend key_store.VALID_PROVIDERS.
const PROVIDERS: { id: string; label: string; hint: string }[] = [
  { id: 'google',      label: 'Google (Gemini)', hint: 'aistudio.google.com/apikey' },
  { id: 'groq',        label: 'Groq',            hint: 'console.groq.com/keys' },
  { id: 'cerebras',    label: 'Cerebras',        hint: 'cloud.cerebras.ai' },
  { id: 'huggingface', label: 'Hugging Face',    hint: 'huggingface.co/settings/tokens' },
  { id: 'github',      label: 'GitHub Models',   hint: 'github.com/settings/tokens' },
  { id: 'openrouter',  label: 'OpenRouter',      hint: 'openrouter.ai/keys' },
]

// Additional free-tier providers, collapsed by default so the common case stays
// a short list. Same BYOK storage and behaviour as PROVIDERS above — the only
// difference is presentation.
const MORE_PROVIDERS: { id: string; label: string; hint: string }[] = [
  { id: 'mistral',   label: 'Mistral AI', hint: 'console.mistral.ai/api-keys — ~1B tokens/month free' },
  { id: 'nvidia',    label: 'NVIDIA NIM', hint: 'build.nvidia.com — free tier for NVIDIA Developer Program members' },
  { id: 'zhipu',     label: 'Zhipu (GLM)', hint: 'open.bigmodel.cn — GLM Flash models are free' },
  { id: 'sambanova', label: 'SambaNova',  hint: 'cloud.sambanova.ai — free tier, low daily request cap' },
  { id: 'kluster',   label: 'Kluster AI', hint: 'platform.kluster.ai/apikeys — limits undocumented' },
]

// Web search providers (agent's web_search tool, Phase A / A.3). Optional —
// without either, web_search is simply absent from the agent's toolset.
// Preference order when both are configured: Tavily, then Brave.
const SEARCH_PROVIDERS: { id: string; label: string; hint: string }[] = [
  { id: 'tavily', label: 'Tavily',       hint: 'app.tavily.com — free tier available' },
  { id: 'brave',  label: 'Brave Search', hint: 'brave.com/search/api' },
]

function ProviderRow({
  id,
  label,
  hint,
  isConfigured,
  isBusy,
  activeHint,
  onToggleHint,
  onRemove,
  error,
  children,
}: {
  id: string
  label: string
  hint: string
  isConfigured: boolean
  isBusy: boolean
  activeHint: string | null
  onToggleHint: (id: string) => void
  onRemove: () => void
  error?: string | null
  children: ReactNode
}) {
  return (
    <div className="p-3 space-y-2">
      {/* Row 1: Title & Help Button */}
      <div className="flex items-center gap-1.5">
        <p className="text-xs font-medium text-theme-text">{label}</p>
        <button
          type="button"
          onClick={() => onToggleHint(id)}
          className={`p-0.5 rounded text-theme-text-muted hover:text-theme-text hover:bg-theme-bg/50 transition-all focus:outline-none cursor-pointer ${
            activeHint === id ? 'text-theme-brand bg-theme-bg/60 border border-theme-border/40' : ''
          }`}
          title="Show guide"
        >
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-3.5 h-3.5">
            <path strokeLinecap="round" strokeLinejoin="round" d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9 5.25h.008v.008H12v-.008z" />
          </svg>
        </button>
      </div>

      {/* Row 2: Hint text (conditional) */}
      {activeHint === id && (
        <p className="text-[10px] text-theme-text-muted bg-theme-bg/40 border border-theme-border/30 rounded-lg p-2 animate-in fade-in slide-in-from-top-1 duration-200">
          {hint}
        </p>
      )}

      {/* Row 3: Configured badge & Remove button (conditional) */}
      {isConfigured && (
        <div className="flex flex-wrap items-center justify-between gap-2 pt-0.5 w-full">
          <span className="text-[9px] font-semibold uppercase tracking-wide text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded-full shrink-0 select-none">
            Configured
          </span>
          <button
            type="button"
            onClick={onRemove}
            disabled={isBusy}
            className="text-[10px] px-2 py-0.5 bg-theme-bg border border-red-500/40 rounded-md text-red-500 hover:bg-red-500/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0 cursor-pointer"
          >
            Remove
          </button>
        </div>
      )}

      {/* Row 4: Inputs (via children) */}
      <div className="pt-1">{children}</div>

      {/* Row 5: Per-provider error */}
      {error && <p className="text-[10px] text-red-500">{error}</p>}
    </div>
  )
}

export default function ApiKeysSection({ onKeysChanged }: { onKeysChanged?: () => void }) {
  const { login } = useAuth()
  const [configured, setConfigured] = useState<string[]>([])
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})

  // Drive link status: null = loading, then true/false. Drive is mandatory
  // storage, so this is the first, most prominent row.
  const [driveConnected, setDriveConnected] = useState<boolean | null>(null)

  function setError(id: string, msg: string | null) {
    setErrors((e) => msg ? { ...e, [id]: msg } : Object.fromEntries(Object.entries(e).filter(([k]) => k !== id)))
  }

  // Kaggle status & input drafts
  const [kaggleHasCreds, setKaggleHasCreds] = useState(false)
  const [kaggleUsername, setKaggleUsername] = useState('')
  const [kaggleApiToken, setKaggleApiToken] = useState('')

  const [activeHint, setActiveHint] = useState<string | null>(null)
  const [showMore, setShowMore] = useState(false)

  function toggleHint(id: string) {
    setActiveHint((h) => (h === id ? null : id))
  }

  async function refresh() {
    try {
      const [keys, kaggle] = await Promise.all([getKeys(), getKaggleConfig()])
      setConfigured(keys)
      setKaggleHasCreds(kaggle.has_creds)
    } catch {
      setError('__global', 'Could not load saved keys.')
    }
  }

  // Isolated from refresh() so a Drive-status failure never blanks the keys list.
  async function refreshDrive() {
    try {
      const { connected } = await getDriveStatus()
      setDriveConnected(connected)
    } catch {
      setDriveConnected(false)
    }
  }

  useEffect(() => {
    refresh()
    refreshDrive()
  }, [])

  function handleConnectDrive() {
    // Re-runs the Google OAuth consent (which requests drive.file) and stores
    // fresh Drive tokens on callback. Redirects the page to Google, so there's
    // nothing to await here.
    setError('drive', null)
    login().catch(() => setError('drive', 'Could not start Google sign-in.'))
  }

  async function handleSave(provider: string) {
    const value = (drafts[provider] || '').trim()
    if (!value) return
    setBusy(provider)
    setError(provider, null)
    try {
      await apiSetKey(provider, value)
      setDrafts((d) => ({ ...d, [provider]: '' }))
      await refresh()
      onKeysChanged?.()
    } catch {
      setError(provider, `Failed to save ${provider} key.`)
    } finally {
      setBusy(null)
    }
  }

  async function handleDelete(provider: string) {
    setBusy(provider)
    setError(provider, null)
    try {
      await apiDeleteKey(provider)
      await refresh()
      onKeysChanged?.()
    } catch {
      setError(provider, `Failed to delete ${provider} key.`)
    } finally {
      setBusy(null)
    }
  }

  async function handleSaveKaggle() {
    const username = kaggleUsername.trim()
    const token = kaggleApiToken.trim()
    if (!username || (!kaggleHasCreds && !token)) return
    setBusy('kaggle')
    setError('kaggle', null)
    try {
      await setKaggleConfig({ username, api_token: token })
      setKaggleUsername('')
      setKaggleApiToken('')
      await refresh()
      onKeysChanged?.()
    } catch {
      setError('kaggle', 'Failed to save Kaggle credentials.')
    } finally {
      setBusy(null)
    }
  }

  async function handleDeleteKaggle() {
    setBusy('kaggle')
    setError('kaggle', null)
    try {
      await deleteKaggleConfig()
      setKaggleUsername('')
      setKaggleApiToken('')
      await refresh()
      onKeysChanged?.()
    } catch {
      setError('kaggle', 'Failed to delete Kaggle credentials.')
    } finally {
      setBusy(null)
    }
  }

  // Shared renderer for a password-input provider row. Used by the core
  // provider list, the collapsed "more providers" list, and the search
  // providers list — identical behaviour in all three, so it lives in one
  // place rather than being copy-pasted per section.
  function renderKeyRow({ id, label, hint }: { id: string; label: string; hint: string }) {
    const isSet = configured.includes(id)
    return (
      <ProviderRow
        key={id}
        id={id}
        label={label}
        hint={hint}
        isConfigured={isSet}
        isBusy={busy === id}
        activeHint={activeHint}
        onToggleHint={toggleHint}
        onRemove={() => handleDelete(id)}
        error={errors[id]}
      >
        <div className="flex items-center gap-2 w-full">
          <input
            type="password"
            value={drafts[id] || ''}
            onChange={(e) => setDrafts((d) => ({ ...d, [id]: e.target.value }))}
            onKeyDown={(e) => e.key === 'Enter' && handleSave(id)}
            placeholder={isSet ? 'New key' : 'Paste key'}
            autoComplete="off"
            className="flex-1 min-w-0 bg-theme-bg border border-theme-border rounded-lg px-3 py-1.5 text-xs text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-brand/50"
          />
          <button
            type="button"
            onClick={() => handleSave(id)}
            disabled={!(drafts[id] || '').trim() || busy === id}
            className="px-3 py-1.5 text-xs bg-theme-brand text-theme-brand-text rounded-lg hover:opacity-90 transition-opacity font-semibold disabled:opacity-40 disabled:cursor-not-allowed shrink-0 cursor-pointer"
          >
            {busy === id ? '…' : 'Save'}
          </button>
        </div>
      </ProviderRow>
    )
  }

  const configuredMoreCount = MORE_PROVIDERS.filter((p) => configured.includes(p.id)).length

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-[10px] font-semibold uppercase tracking-widest text-theme-text-muted mb-1">API Keys (BYOK)</h2>
        <p className="text-[10px] text-theme-text-muted leading-relaxed">
          Bring your own provider keys. Keys are encrypted at rest and used only by the
          backend to make requests on your behalf — they are never shown again after saving.
        </p>
      </div>

      {errors['__global'] && (
        <p className="text-[10px] text-red-500">{errors['__global']}</p>
      )}

      <div className="bg-theme-surface border border-theme-border/50 rounded-xl divide-y divide-theme-border/30">

        {/* Google Drive — mandatory storage backend; first and most prominent row */}
        <div className="p-3 space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-1.5">
              <p className="text-xs font-medium text-theme-text">Google Drive</p>
              {driveConnected === true && (
                <span className="text-[9px] font-semibold uppercase tracking-wide text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded-full shrink-0 select-none">
                  Connected
                </span>
              )}
              {driveConnected === false && (
                <span className="text-[9px] font-semibold uppercase tracking-wide text-amber-600 dark:text-amber-400 bg-amber-500/10 px-1.5 py-0.5 rounded-full shrink-0 select-none">
                  Not connected
                </span>
              )}
            </div>
            <button
              type="button"
              onClick={handleConnectDrive}
              className="px-3 py-1.5 text-xs bg-theme-brand text-theme-brand-text rounded-lg hover:opacity-90 transition-opacity font-semibold shrink-0 cursor-pointer"
            >
              {driveConnected ? 'Reconnect' : 'Connect'}
            </button>
          </div>
          <p className="text-[10px] text-theme-text-muted leading-relaxed">
            PAWN stores your conversations and uploads in your own Google Drive. This is
            required — {driveConnected ? 'reconnect if chats stop saving.' : 'connect it to start saving your chats.'}
          </p>
          {errors['drive'] && <p className="text-[10px] text-red-500">{errors['drive']}</p>}
        </div>

        {/* Kaggle Credentials */}
        <ProviderRow
          id="kaggle"
          label="Kaggle API Credentials"
          hint="kaggle.com settings → Account → API Token"
          isConfigured={kaggleHasCreds}
          isBusy={busy === 'kaggle'}
          activeHint={activeHint}
          onToggleHint={toggleHint}
          onRemove={handleDeleteKaggle}
          error={errors['kaggle']}
        >
          <div className="flex flex-col gap-2 w-full">
            <input
              type="text"
              value={kaggleUsername}
              onChange={(e) => setKaggleUsername(e.target.value)}
              placeholder="Kaggle username"
              className="w-full bg-theme-bg border border-theme-border rounded-lg px-3 py-1.5 text-xs text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-brand/50"
            />
            <div className="flex items-center gap-2 w-full">
              <input
                type="password"
                value={kaggleApiToken}
                onChange={(e) => setKaggleApiToken(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSaveKaggle()}
                placeholder={kaggleHasCreds ? 'New token' : 'Kaggle API token'}
                autoComplete="off"
                className="flex-1 min-w-0 bg-theme-bg border border-theme-border rounded-lg px-3 py-1.5 text-xs text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-brand/50"
              />
              <button
                type="button"
                onClick={handleSaveKaggle}
                disabled={!kaggleUsername.trim() || (!kaggleHasCreds && !kaggleApiToken.trim()) || busy === 'kaggle'}
                className="px-3 py-1.5 text-xs bg-theme-brand text-theme-brand-text rounded-lg hover:opacity-90 transition-opacity font-semibold disabled:opacity-40 disabled:cursor-not-allowed shrink-0 cursor-pointer"
              >
                {busy === 'kaggle' ? '…' : 'Save'}
              </button>
            </div>
          </div>
        </ProviderRow>

        {/* LLM provider keys */}
        {PROVIDERS.map(renderKeyRow)}

        {/* Additional free-tier providers — collapsed by default */}
        <div className="p-3">
          <button
            type="button"
            onClick={() => setShowMore((s) => !s)}
            className="flex items-center gap-1.5 text-[10px] font-medium text-theme-text-muted hover:text-theme-text transition-colors cursor-pointer"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={2}
              stroke="currentColor"
              className={`w-3 h-3 transition-transform ${showMore ? 'rotate-90' : ''}`}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
            </svg>
            {showMore ? 'Hide' : 'Show'} {MORE_PROVIDERS.length} more free providers
            {configuredMoreCount > 0 && (
              <span className="text-[9px] font-semibold uppercase tracking-wide text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded-full select-none">
                {configuredMoreCount} configured
              </span>
            )}
          </button>
        </div>

        {showMore && MORE_PROVIDERS.map(renderKeyRow)}

      </div>

      <div>
        <h2 className="text-[10px] font-semibold uppercase tracking-widest text-theme-text-muted mb-1">Search (optional)</h2>
        <p className="text-[10px] text-theme-text-muted leading-relaxed">
          Lets the assistant search the web for current information. Without one of these,
          it answers from its own knowledge only — no error, no degraded chat.
        </p>
      </div>

      <div className="bg-theme-surface border border-theme-border/50 rounded-xl divide-y divide-theme-border/30">
        {SEARCH_PROVIDERS.map(renderKeyRow)}
      </div>
    </section>
  )
}
