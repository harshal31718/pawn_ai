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
import { useAppContext } from '../contexts/AppContext'
import { useAuth } from '../contexts/AuthContext'

/** 2026-07-23 redesign: one consistent 2-row layout for every provider,
 *  configured or not (a collapsed single-row variant for unconfigured
 *  providers was tried and reverted -- looked worse in practice).
 *
 *  Row 1: name (col 1) + "?" hint toggle (col 2) + right-corner action
 *         button (col 3) -- "Reconnect" for OAuth providers (Drive),
 *         "Remove" for BYOK providers (only shown once configured).
 *  Row 2: input(s) (col 1) + Save button (col 2, right corner). Omitted
 *         entirely for providers with nothing to save (Drive -- its
 *         "action" IS row 1's Reconnect button).
 */
function ProviderRow({
  id,
  name,
  hint,
  isConfigured,
  configuredLabel = 'Configured',
  isBusy,
  activeHint,
  onToggleHint,
  actionLabel,
  onAction,
  onSave,
  saveDisabled,
  error,
  children,
}: {
  id: string
  name: string
  hint?: string
  isConfigured: boolean
  configuredLabel?: string
  isBusy: boolean
  activeHint: string | null
  onToggleHint: (id: string) => void
  actionLabel?: string
  onAction?: () => void
  onSave?: () => void
  saveDisabled?: boolean
  error?: string | null
  children?: ReactNode
}) {
  const hintToggle = hint && (
    <button
      type="button"
      onClick={() => onToggleHint(id)}
      className={`p-0.5 rounded text-theme-text-muted hover:text-theme-text hover:bg-theme-bg/50 transition-all focus:outline-none cursor-pointer shrink-0 ${
        activeHint === id ? 'text-theme-brand bg-theme-bg/60 border border-theme-border/40' : ''
      }`}
      title="Show guide"
    >
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-3.5 h-3.5">
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9 5.25h.008v.008H12v-.008z" />
      </svg>
    </button>
  )
  const hintText = hint && activeHint === id && (
    <p className="text-[10px] text-theme-text-muted truncate animate-in fade-in duration-200">
      {hint}
    </p>
  )
  const saveButton = onSave && (
    <button
      type="button"
      onClick={onSave}
      disabled={saveDisabled || isBusy}
      className="w-[71.5px] py-1 text-[10px] bg-theme-brand text-theme-brand-text rounded-md hover:opacity-90 transition-colors font-semibold disabled:opacity-40 disabled:cursor-not-allowed shrink-0 cursor-pointer text-center"
    >
      {isBusy ? '…' : 'Save'}
    </button>
  )

  return (
    <div className="p-3 space-y-2">
      {/* Row 1: name + hint toggle + inline hint text (left, grows) /
          configured badge + action (right, fixed) -- the hint, when open,
          flows in the SAME line right after the "?" icon, not a separate
          line below. */}
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-1.5 min-w-0 flex-1">
          <p className="text-xs font-medium text-theme-text shrink-0">{name}</p>
          {hintToggle}
          {hintText}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {isConfigured && (
            <span
              className={`text-[9px] font-semibold uppercase tracking-wide text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 py-0.5 rounded-full select-none ${
                configuredLabel === 'Connected' ? 'px-2' : 'px-1.5'
              }`}
            >
              {configuredLabel}
            </span>
          )}
          {actionLabel && onAction && (isConfigured || actionLabel !== 'Remove') && (
            <button
              type="button"
              onClick={onAction}
              disabled={isBusy}
              className={`text-[10px] py-1 rounded-md font-semibold cursor-pointer transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                actionLabel === 'Remove'
                  ? 'px-4 bg-theme-bg border border-red-500/40 text-red-500 hover:bg-red-500/10'
                  : 'px-2.5 bg-theme-brand text-theme-brand-text hover:opacity-90'
              }`}
            >
              {isBusy ? '…' : actionLabel}
            </button>
          )}
        </div>
      </div>

      {/* Row 2: input(s) + Save -- omitted when there's nothing to save. */}
      {children && (
        <div className="flex items-center gap-2 w-full">
          <div className="flex-1 min-w-0">{children}</div>
          {saveButton}
        </div>
      )}

      {error && <p className="text-[10px] text-red-500">{error}</p>}
    </div>
  )
}

export default function ApiKeysSection({
  onKeysChanged,
  search,
}: {
  onKeysChanged?: () => void
  search: string
}) {
  const { login } = useAuth()
  const { providers } = useAppContext()
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

  // A provider's "?" hint text -- derived from the registry entry rather than
  // a hardcoded per-provider string, so a new provider needs zero UI code.
  function hintFor(p: { free_tier_note: string | null; signup_link: string }): string {
    return [p.free_tier_note, p.signup_link].filter(Boolean).join(' — ')
  }

  // Shared renderer for a single-key-input provider row (every LLM/search
  // provider). Kaggle and Drive are special-cased below (different input
  // shape / no key input at all).
  function renderKeyRow(id: string, name: string, hint: string) {
    const isSet = configured.includes(id)
    return (
      <ProviderRow
        key={id}
        id={id}
        name={name}
        hint={hint}
        isConfigured={isSet}
        isBusy={busy === id}
        activeHint={activeHint}
        onToggleHint={toggleHint}
        actionLabel="Remove"
        onAction={() => handleDelete(id)}
        onSave={() => handleSave(id)}
        saveDisabled={!(drafts[id] || '').trim()}
        error={errors[id]}
      >
        <input
          type="password"
          value={drafts[id] || ''}
          onChange={(e) => setDrafts((d) => ({ ...d, [id]: e.target.value }))}
          onKeyDown={(e) => e.key === 'Enter' && handleSave(id)}
          placeholder={isSet ? 'New key' : 'Paste key'}
          autoComplete="off"
          className="w-full bg-theme-bg border border-theme-border rounded-lg px-3 py-1.5 text-xs text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-brand/50"
        />
      </ProviderRow>
    )
  }

  const driveProvider = providers.find((p) => p.id === 'google_drive')
  const kaggleProvider = providers.find((p) => p.id === 'kaggle')
  // One combined, filterable list -- chat (LLM) and internet (search)
  // providers used to be two separately-headed sections; now they're just
  // rows in the same list, per the user's follow-up call.
  const keyProviders = providers.filter(
    (p) => p.capabilities.includes('chat') || p.capabilities.includes('internet'),
  )

  // Drive + Kaggle join the same searchable/sortable pool as every other
  // provider (per the user's follow-up calls): without a search query,
  // configured/connected items float to the top (stable sort -- Drive and
  // Kaggle still land first among configured items since they're first in
  // this array); with a query, every row (Drive/Kaggle included) is
  // filtered by relevance like anything else, so they hide when irrelevant.
  type Row = { kind: 'drive' | 'kaggle' | 'key'; id: string; name: string; isConfigured: boolean }
  const allRows: Row[] = [
    { kind: 'drive', id: 'drive', name: driveProvider?.name ?? 'Google Drive', isConfigured: driveConnected === true },
    { kind: 'kaggle', id: 'kaggle', name: kaggleProvider?.name ?? 'Kaggle', isConfigured: kaggleHasCreds },
    ...keyProviders.map((p): Row => ({ kind: 'key', id: p.id, name: p.name, isConfigured: configured.includes(p.id) })),
  ]

  const query = search.trim().toLowerCase()
  const visibleRows = query
    ? allRows.filter((r) => r.name.toLowerCase().includes(query) || r.id.toLowerCase().includes(query))
    : [...allRows].sort((a, b) => Number(b.isConfigured) - Number(a.isConfigured))

  return (
    <section className="space-y-4">
      {errors['__global'] && (
        <p className="text-[10px] text-red-500">{errors['__global']}</p>
      )}

      <div className="bg-theme-surface border border-theme-border/50 rounded-xl divide-y divide-theme-border/30">
        {visibleRows.map((row) => {
          if (row.kind === 'drive') {
            return (
              <ProviderRow
                key="drive"
                id="drive"
                name={row.name}
                hint="PAWN stores your conversations and uploads in your own Google Drive. This is required."
                isConfigured={driveConnected === true}
                configuredLabel="Connected"
                isBusy={false}
                activeHint={activeHint}
                onToggleHint={toggleHint}
                actionLabel={driveConnected ? 'Reconnect' : 'Connect'}
                onAction={handleConnectDrive}
                error={errors['drive']}
              />
            )
          }
          if (row.kind === 'kaggle') {
            return (
              <ProviderRow
                key="kaggle"
                id="kaggle"
                name={row.name}
                hint={kaggleProvider ? hintFor(kaggleProvider) : undefined}
                isConfigured={kaggleHasCreds}
                isBusy={busy === 'kaggle'}
                activeHint={activeHint}
                onToggleHint={toggleHint}
                actionLabel="Remove"
                onAction={handleDeleteKaggle}
                onSave={handleSaveKaggle}
                saveDisabled={!kaggleUsername.trim() || (!kaggleHasCreds && !kaggleApiToken.trim())}
                error={errors['kaggle']}
              >
                {/* Username + token in one line, per the locked row-2 design. */}
                <div className="flex items-center gap-2 w-full">
                  <input
                    type="text"
                    value={kaggleUsername}
                    onChange={(e) => setKaggleUsername(e.target.value)}
                    placeholder="Kaggle username"
                    className="flex-1 min-w-0 bg-theme-bg border border-theme-border rounded-lg px-3 py-1.5 text-xs text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-brand/50"
                  />
                  <input
                    type="password"
                    value={kaggleApiToken}
                    onChange={(e) => setKaggleApiToken(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleSaveKaggle()}
                    placeholder={kaggleHasCreds ? 'New token' : 'API token'}
                    autoComplete="off"
                    className="flex-1 min-w-0 bg-theme-bg border border-theme-border rounded-lg px-3 py-1.5 text-xs text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-brand/50"
                  />
                </div>
              </ProviderRow>
            )
          }
          const p = keyProviders.find((kp) => kp.id === row.id)!
          return renderKeyRow(p.id, p.name, hintFor(p))
        })}
        {query && visibleRows.length === 0 && (
          <p className="p-3 text-[10px] text-theme-text-muted">No providers match "{search}".</p>
        )}
      </div>
    </section>
  )
}
