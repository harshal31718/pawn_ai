import { useEffect, useState } from 'react'
import { getKeys, setKey as apiSetKey, deleteKey as apiDeleteKey } from '../api/client'

// Mirrors backend key_store.VALID_PROVIDERS.
const PROVIDERS: { id: string; label: string; hint: string }[] = [
  { id: 'google',      label: 'Google (Gemini)', hint: 'aistudio.google.com/apikey' },
  { id: 'groq',        label: 'Groq',            hint: 'console.groq.com/keys' },
  { id: 'cerebras',    label: 'Cerebras',        hint: 'cloud.cerebras.ai' },
  { id: 'huggingface', label: 'Hugging Face',    hint: 'huggingface.co/settings/tokens' },
  { id: 'github',      label: 'GitHub Models',   hint: 'github.com/settings/tokens' },
  { id: 'openrouter',  label: 'OpenRouter',      hint: 'openrouter.ai/keys' },
]

export default function ApiKeysSection({ onKeysChanged }: { onKeysChanged?: () => void }) {
  const [configured, setConfigured] = useState<string[]>([])
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function refresh() {
    try {
      setConfigured(await getKeys())
    } catch {
      setError('Could not load saved keys.')
    }
  }

  useEffect(() => { refresh() }, [])

  async function handleSave(provider: string) {
    const value = (drafts[provider] || '').trim()
    if (!value) return
    setBusy(provider)
    setError(null)
    try {
      await apiSetKey(provider, value)
      setDrafts((d) => ({ ...d, [provider]: '' }))
      await refresh()
      onKeysChanged?.()
    } catch {
      setError(`Failed to save ${provider} key.`)
    } finally {
      setBusy(null)
    }
  }

  async function handleDelete(provider: string) {
    setBusy(provider)
    setError(null)
    try {
      await apiDeleteKey(provider)
      await refresh()
      onKeysChanged?.()
    } catch {
      setError(`Failed to delete ${provider} key.`)
    } finally {
      setBusy(null)
    }
  }

  return (
    <section>
      <h2 className="text-[10px] font-semibold uppercase tracking-widest text-theme-text-muted mb-3">API Keys (BYOK)</h2>
      <p className="text-[10px] text-theme-text-muted mb-3 leading-relaxed">
        Bring your own provider keys. Keys are encrypted at rest and used only by the
        backend to make requests on your behalf — they are never shown again after saving.
      </p>
      {error && (
        <p className="text-[10px] text-red-500 mb-2">{error}</p>
      )}
      <div className="bg-theme-surface border border-theme-border/50 rounded-xl divide-y divide-theme-border/30">
        {PROVIDERS.map(({ id, label, hint }) => {
          const isSet = configured.includes(id)
          return (
            <div key={id} className="p-4 space-y-2">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-medium text-theme-text flex items-center gap-2">
                    {label}
                    {isSet && (
                      <span className="text-[9px] font-semibold uppercase tracking-wide text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded-full">
                        Configured
                      </span>
                    )}
                  </p>
                  <p className="text-[10px] text-theme-text-muted mt-0.5">{hint}</p>
                </div>
                {isSet && (
                  <button
                    type="button"
                    onClick={() => handleDelete(id)}
                    disabled={busy === id}
                    className="text-[10px] px-2 py-1 bg-theme-bg border border-red-500/40 rounded-md text-red-500 hover:bg-red-500/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
                  >
                    Remove
                  </button>
                )}
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="password"
                  value={drafts[id] || ''}
                  onChange={(e) => setDrafts((d) => ({ ...d, [id]: e.target.value }))}
                  onKeyDown={(e) => e.key === 'Enter' && handleSave(id)}
                  placeholder={isSet ? 'Enter a new key to replace' : 'Paste your API key'}
                  autoComplete="off"
                  className="flex-1 bg-theme-bg border border-theme-border rounded-lg px-3 py-1.5 text-xs text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-brand/50"
                />
                <button
                  type="button"
                  onClick={() => handleSave(id)}
                  disabled={!(drafts[id] || '').trim() || busy === id}
                  className="px-3 py-1.5 text-xs bg-theme-brand text-theme-brand-text rounded-lg hover:opacity-90 transition-opacity font-semibold disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
                >
                  {busy === id ? '…' : 'Save'}
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}
