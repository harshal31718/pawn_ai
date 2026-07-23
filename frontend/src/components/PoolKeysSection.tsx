import { useEffect, useState } from 'react'
import { getPoolKeys, setPoolKey, deletePoolKey, type PoolKeyRow } from '../api/client'
import { useAppContext } from '../contexts/AppContext'

/** 2026-07-23: admin-only "Providers (Pool)" tab -- same row/search visual
 *  language as ApiKeysSection.tsx (BYOK), but reading/writing the operator's
 *  shared pool keys via the admin routes instead of each user's own BYOK
 *  keys. No Drive/Kaggle here -- pool sharing only applies to the `type ===
 *  "pool"` (chat/LLM) providers; BYOK-only providers have no pool concept.
 *  Deliberately does NOT reuse ApiKeysSection's <ProviderRow>/<AdminPage>'s
 *  enable-disable toggle -- kept to exactly the same minimal shape as BYOK
 *  (name/hint/Remove, input/Save) per the user's explicit "visually the
 *  same" call; AdminPage.tsx still exists separately for saturation/enable
 *  controls. */
function PoolProviderRow({
  id,
  name,
  isConfigured,
  isBusy,
  activeHint,
  onToggleHint,
  hint,
  onRemove,
  onSave,
  saveDisabled,
  error,
  value,
  onChange,
}: {
  id: string
  name: string
  isConfigured: boolean
  isBusy: boolean
  activeHint: string | null
  onToggleHint: (id: string) => void
  hint?: string
  onRemove: () => void
  onSave: () => void
  saveDisabled: boolean
  error?: string | null
  value: string
  onChange: (v: string) => void
}) {
  return (
    <div className="p-3 space-y-2">
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-1.5 min-w-0 flex-1">
          <p className="text-xs font-medium text-theme-text shrink-0">{name}</p>
          {hint && (
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
          )}
          {hint && activeHint === id && (
            <p className="text-[10px] text-theme-text-muted truncate animate-in fade-in duration-200">{hint}</p>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {isConfigured && (
            <span className="text-[9px] font-semibold uppercase tracking-wide text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded-full select-none">
              Configured
            </span>
          )}
          {isConfigured && (
            <button
              type="button"
              onClick={onRemove}
              disabled={isBusy}
              className="text-[10px] px-4 py-1 rounded-md font-semibold cursor-pointer transition-colors disabled:opacity-40 disabled:cursor-not-allowed bg-theme-bg border border-red-500/40 text-red-500 hover:bg-red-500/10"
            >
              {isBusy ? '…' : 'Remove'}
            </button>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2 w-full">
        <input
          type="password"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && onSave()}
          placeholder={isConfigured ? 'New key' : 'Paste key'}
          autoComplete="off"
          className="flex-1 min-w-0 bg-theme-bg border border-theme-border rounded-lg px-3 py-1.5 text-xs text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-brand/50"
        />
        <button
          type="button"
          onClick={onSave}
          disabled={saveDisabled || isBusy}
          className="w-[71.5px] py-1 text-[10px] bg-theme-brand text-theme-brand-text rounded-md hover:opacity-90 transition-colors font-semibold disabled:opacity-40 disabled:cursor-not-allowed shrink-0 cursor-pointer text-center"
        >
          {isBusy ? '…' : 'Save'}
        </button>
      </div>
      {error && <p className="text-[10px] text-red-500">{error}</p>}
    </div>
  )
}

export default function PoolKeysSection({ search }: { search: string }) {
  const { providers } = useAppContext()
  const [poolRows, setPoolRows] = useState<PoolKeyRow[]>([])
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [activeHint, setActiveHint] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  function setError(id: string, msg: string | null) {
    setErrors((e) => (msg ? { ...e, [id]: msg } : Object.fromEntries(Object.entries(e).filter(([k]) => k !== id))))
  }

  async function refresh() {
    setLoadError(null)
    try {
      const poolRows = await getPoolKeys()
      setPoolRows(poolRows)
    } catch {
      setLoadError('Could not load pool keys — this account may not have admin access.')
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  function toggleHint(id: string) {
    setActiveHint((h) => (h === id ? null : id))
  }

  async function handleSave(provider: string) {
    const value = (drafts[provider] || '').trim()
    if (!value) return
    setBusy(provider)
    setError(provider, null)
    try {
      await setPoolKey(provider, value)
      setDrafts((d) => ({ ...d, [provider]: '' }))
      await refresh()
    } catch {
      setError(provider, `Failed to save the ${provider} pool key.`)
    } finally {
      setBusy(null)
    }
  }

  async function handleRemove(provider: string) {
    setBusy(provider)
    setError(provider, null)
    try {
      await deletePoolKey(provider)
      await refresh()
    } catch {
      setError(provider, `Failed to remove the ${provider} pool key.`)
    } finally {
      setBusy(null)
    }
  }

  function hintFor(p: { free_tier_note: string | null; signup_link: string }): string {
    return [p.free_tier_note, p.signup_link].filter(Boolean).join(' — ')
  }

  // Pool sharing only applies to type === "pool" providers -- no Drive, no
  // Kaggle, no search-only (internet) providers here.
  const poolProviders = providers.filter((p) => p.type === 'pool')
  const configuredIds = new Set(poolRows.filter((r) => r.configured).map((r) => r.provider))

  const query = search.trim().toLowerCase()
  const filtered = query
    ? poolProviders.filter((p) => p.name.toLowerCase().includes(query) || p.id.toLowerCase().includes(query))
    : [...poolProviders].sort((a, b) => Number(configuredIds.has(b.id)) - Number(configuredIds.has(a.id)))

  return (
    <section className="space-y-4">
      <div className="bg-theme-surface border border-theme-border/50 rounded-xl divide-y divide-theme-border/30">
        {loadError && <p className="p-3 text-[10px] text-red-500">{loadError}</p>}

        {filtered.map((p) => (
          <PoolProviderRow
            key={p.id}
            id={p.id}
            name={p.name}
            hint={hintFor(p)}
            isConfigured={configuredIds.has(p.id)}
            isBusy={busy === p.id}
            activeHint={activeHint}
            onToggleHint={toggleHint}
            onRemove={() => handleRemove(p.id)}
            onSave={() => handleSave(p.id)}
            saveDisabled={!(drafts[p.id] || '').trim()}
            error={errors[p.id]}
            value={drafts[p.id] || ''}
            onChange={(v) => setDrafts((d) => ({ ...d, [p.id]: v }))}
          />
        ))}
        {query && filtered.length === 0 && (
          <p className="p-3 text-[10px] text-theme-text-muted">No providers match "{search}".</p>
        )}
      </div>
    </section>
  )
}
