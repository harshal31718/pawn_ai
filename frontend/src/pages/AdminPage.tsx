import { useEffect, useState } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import {
  getPoolKeys,
  setPoolKey,
  deletePoolKey,
  patchPoolKey,
  getAdminStats,
  type PoolKeyRow,
} from '../api/client'
import type { LayoutContext } from './Layout'

// Mirrors backend pool_key_store.POOL_VALID_PROVIDERS.
const PROVIDERS: { id: string; label: string }[] = [
  { id: 'google', label: 'Google (Gemini)' },
  { id: 'groq', label: 'Groq' },
  { id: 'cerebras', label: 'Cerebras' },
  { id: 'huggingface', label: 'Hugging Face' },
  { id: 'github', label: 'GitHub Models' },
  { id: 'openrouter', label: 'OpenRouter' },
  { id: 'mistral', label: 'Mistral AI' },
  { id: 'nvidia', label: 'NVIDIA NIM' },
  { id: 'zhipu', label: 'Zhipu (GLM)' },
  { id: 'sambanova', label: 'SambaNova' },
  { id: 'kluster', label: 'Kluster AI' },
]

/** PAWN 2.0 Phase B.6: admin page -- pool-key CRUD + per-provider enable/
 *  disable, and a read-only registered-user count. Mirrors
 *  ApiKeysSection.tsx's row pattern (password input, Save/Remove, Configured
 *  badge) rather than reusing it directly -- that component is BYOK-specific
 *  (per-user keys, no enable toggle); this is operator-owned pool state.
 *  Frontend gating here is UX only (Sidebar shows this entry only when
 *  is_admin) -- the real control is backend require_admin, so a non-admin
 *  hitting this page directly still gets 403s from every request below. */
export default function AdminPage() {
  const navigate = useNavigate()
  const { isSidebarOpen, setIsSidebarOpen } = useOutletContext<LayoutContext>()
  const [rows, setRows] = useState<Record<string, PoolKeyRow>>({})
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [registeredUsers, setRegisteredUsers] = useState<number | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  function setError(id: string, msg: string | null) {
    setErrors((e) => (msg ? { ...e, [id]: msg } : Object.fromEntries(Object.entries(e).filter(([k]) => k !== id))))
  }

  async function refresh() {
    setLoadError(null)
    try {
      const [poolRows, stats] = await Promise.all([getPoolKeys(), getAdminStats()])
      setRows(Object.fromEntries(poolRows.map((r) => [r.provider, r])))
      setRegisteredUsers(stats.registered_users)
    } catch {
      setLoadError('Could not load admin data — this account may not have admin access.')
    }
  }

  useEffect(() => {
    refresh()
  }, [])

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

  async function handleToggleEnabled(provider: string, enabled: boolean) {
    setBusy(provider)
    setError(provider, null)
    try {
      await patchPoolKey(provider, { enabled })
      await refresh()
    } catch {
      setError(provider, `Failed to ${enabled ? 'enable' : 'disable'} ${provider}.`)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden relative bg-theme-bg">
      {/* Floating Top Header -- same pill chip as SettingsPage.tsx/ProvidersPage.tsx. */}
      <header className="absolute top-0 left-0 right-0 z-30 pointer-events-none p-4 flex items-center justify-between w-full">
        <div className="flex items-center gap-2 h-7 pl-2 pr-3 bg-theme-surface border border-theme-border/60 rounded-xl shadow-md pointer-events-auto z-20 transition-all">
          {!isSidebarOpen && (
            <button
              type="button"
              onClick={() => setIsSidebarOpen(true)}
              className="md:hidden rounded-full text-theme-text-muted hover:bg-theme-bg/50 hover:text-theme-text transition-colors focus:outline-none flex items-center justify-center"
              title="Open sidebar"
            >
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
              </svg>
            </button>
          )}
          <button
            type="button"
            onClick={() => navigate('/chat')}
            className="rounded-full text-theme-text-muted hover:bg-theme-bg/50 hover:text-theme-text transition-colors focus:outline-none flex items-center justify-center"
            title="Back to chat"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
            </svg>
          </button>
          <h1 className="text-xs font-semibold text-theme-text select-none">Admin</h1>
        </div>
      </header>

      <div className="h-full overflow-y-auto pt-14">
        <div className="w-full max-w-3xl mx-auto px-4 sm:px-6 pb-12 space-y-6">
          <p className="text-xs text-theme-text-muted leading-relaxed">
            Manage the shared free-tier key pool every keyless user falls back to, and see
            how many accounts are registered on this deployment.
          </p>

          {loadError && <p className="text-xs text-red-500">{loadError}</p>}

          <div className="bg-theme-surface border border-theme-border/50 rounded-xl p-4">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-theme-text-muted mb-1">
              Registered users
            </p>
            <p className="text-2xl font-semibold text-theme-text">
              {registeredUsers ?? '—'}
            </p>
          </div>

          <div className="bg-theme-surface border border-theme-border/50 rounded-xl divide-y divide-theme-border/30">
            <div className="p-3">
              <h2 className="text-[10px] font-semibold uppercase tracking-widest text-theme-text-muted">
                Pool keys
              </h2>
            </div>
            {PROVIDERS.map(({ id, label }) => {
              const row = rows[id]
              const isConfigured = !!row
              return (
                <div key={id} className="p-3 space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs font-medium text-theme-text">{label}</p>
                    {isConfigured && (
                      <div className="flex items-center gap-2 shrink-0">
                        <span
                          className={`text-[9px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded-full select-none ${
                            row.enabled
                              ? 'text-emerald-600 dark:text-emerald-400 bg-emerald-500/10'
                              : 'text-theme-text-muted bg-theme-bg/60'
                          }`}
                        >
                          {row.enabled ? 'Enabled' : 'Disabled'}
                        </span>
                        <button
                          type="button"
                          onClick={() => handleToggleEnabled(id, !row.enabled)}
                          disabled={busy === id}
                          className="text-[10px] px-2 py-0.5 bg-theme-bg border border-theme-border/50 rounded-md text-theme-text-muted hover:text-theme-text transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                        >
                          {row.enabled ? 'Disable' : 'Enable'}
                        </button>
                        <button
                          type="button"
                          onClick={() => handleRemove(id)}
                          disabled={busy === id}
                          className="text-[10px] px-2 py-0.5 bg-theme-bg border border-red-500/40 rounded-md text-red-500 hover:bg-red-500/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                        >
                          Remove
                        </button>
                      </div>
                    )}
                  </div>
                  <div className="flex gap-2">
                    <input
                      type="password"
                      value={drafts[id] || ''}
                      onChange={(e) => setDrafts((d) => ({ ...d, [id]: e.target.value }))}
                      placeholder={isConfigured ? 'Replace key…' : 'Paste API key…'}
                      className="flex-1 min-w-0 text-xs bg-theme-bg border border-theme-border/50 rounded-lg px-2.5 py-1.5 text-theme-text placeholder:text-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-brand"
                    />
                    <button
                      type="button"
                      onClick={() => handleSave(id)}
                      disabled={busy === id || !(drafts[id] || '').trim()}
                      className="text-xs px-3 py-1.5 bg-theme-brand text-white rounded-lg disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer shrink-0"
                    >
                      Save
                    </button>
                  </div>
                  {errors[id] && <p className="text-[10px] text-red-500">{errors[id]}</p>}
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
