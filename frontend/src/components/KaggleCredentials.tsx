import { useState, useEffect } from 'react'
import { getKaggleConfig, setKaggleConfig, deleteKaggleConfig } from '../api/client'
import { saveDeployed } from '../store/deployedStore'

export default function KaggleCredentials({
  hasCreds,
  onChange,
  onRedeployAll,
  isRedeploying,
}: {
  hasCreds: boolean
  onChange: (hasCreds: boolean) => void
  onRedeployAll: () => void
  isRedeploying: boolean
}) {
  const [username, setUsername] = useState('')
  const [apiToken, setApiToken] = useState('')
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    getKaggleConfig()
      .then((s) => {
        if (active) {
          onChange(s.has_creds)
          if (!s.has_creds) setEditing(true)
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
      saveDeployed({})
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

  return (
    <>
      {hasCreds ? (
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl border border-emerald-500/25 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 select-none shadow-sm">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
          <span className="text-xs font-semibold">Kaggle Connected</span>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onRedeployAll() }}
            disabled={isRedeploying}
            className="p-1 rounded-lg text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/15 transition-colors cursor-pointer flex items-center justify-center ml-1 disabled:opacity-50"
            title="Redeploy all model notebooks"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={2.5}
              stroke="currentColor"
              className={`w-3.5 h-3.5 ${isRedeploying ? 'animate-spin' : ''}`}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
            </svg>
          </button>
          <button
            type="button"
            onClick={() => { setEditing(true); setError(null) }}
            className="p-1 rounded-lg text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/15 transition-colors cursor-pointer flex items-center justify-center ml-1"
            title="Edit credentials"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-3.5 h-3.5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0115.75 21H5.25A2.25 2.25 0 013 18.75V8.25A2.25 2.25 0 015.25 6H10" />
            </svg>
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl border border-amber-500/25 bg-amber-500/10 text-amber-600 dark:text-amber-400 shadow-sm">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
          <span className="text-xs font-semibold">Kaggle Setup Required</span>
          <button
            type="button"
            onClick={() => { setEditing(true); setError(null) }}
            className="px-2 py-0.5 rounded-lg bg-amber-500 text-white dark:text-zinc-950 hover:bg-amber-600 dark:hover:bg-amber-400 text-[10px] font-bold uppercase transition-colors cursor-pointer ml-1"
          >
            Setup
          </button>
        </div>
      )}

      {editing && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs"
          onClick={() => hasCreds && setEditing(false)}
        >
          <div
            className="bg-theme-surface border border-theme-border/60 rounded-2xl p-5 shadow-2xl max-w-sm w-full space-y-4 relative animate-in fade-in zoom-in-95 duration-150"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-semibold text-theme-text uppercase tracking-wider">Kaggle Credentials</h2>
              {hasCreds && (
                <button
                  type="button"
                  onClick={() => { setEditing(false); setError(null) }}
                  className="text-theme-text-muted hover:text-theme-text transition-colors cursor-pointer flex items-center justify-center w-5 h-5 rounded-full hover:bg-theme-bg/50"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" className="w-4 h-4">
                    <path d="M5.28 4.22a.75.75 0 0 0-1.06 1.06L6.94 8l-2.72 2.72a.75.75 0 1 0 1.06 1.06L8 9.06l2.72 2.72a.75.75 0 1 0 1.06-1.06L9.06 8l2.72-2.72a.75.75 0 0 0-1.06-1.06L8 6.94 5.28 4.22Z" />
                  </svg>
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
                className="w-full px-3 py-2 rounded-xl text-xs bg-theme-bg border border-theme-border/60 text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-brand disabled:opacity-60"
              />
              <input
                type="password"
                value={apiToken}
                onChange={(e) => setApiToken(e.target.value)}
                disabled={busy}
                placeholder={hasCreds ? 'API token (saved — enter to replace)' : 'API token'}
                className="w-full px-3 py-2 rounded-xl text-xs bg-theme-bg border border-theme-border/60 text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-brand disabled:opacity-60"
              />
            </div>

            <div className="flex justify-end gap-2 pt-2">
              {hasCreds && (
                <button
                  type="button"
                  onClick={handleRemove}
                  disabled={busy}
                  className="px-4 py-2 rounded-xl text-xs font-semibold bg-theme-bg border border-red-500/40 text-red-500 hover:bg-red-500/10 transition-colors disabled:opacity-60 cursor-pointer"
                >
                  {busy ? 'Removing...' : 'Remove'}
                </button>
              )}
              <button
                type="button"
                onClick={handleSave}
                disabled={busy}
                className="px-4 py-2 rounded-xl text-xs font-semibold bg-theme-brand text-theme-brand-text shadow-sm hover:opacity-90 disabled:opacity-60 cursor-pointer"
              >
                {busy ? 'Saving...' : 'Save Credentials'}
              </button>
            </div>

            {error && <div className="text-xs text-red-600 dark:text-red-400 mt-1 font-medium">{error}</div>}
          </div>
        </div>
      )}
    </>
  )
}
