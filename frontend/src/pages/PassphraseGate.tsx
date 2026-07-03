import { useState, useEffect, type ReactNode } from 'react'
import { fetchSalt } from '../api/client'
import { hasKey, initSession } from '../crypto/session'

/**
 * Passphrase gate — shown once per tab session, after auth and before any
 * conversation loads. Derives the AES-256-GCM key from the user's passphrase
 * plus the server-stored PBKDF2 salt (GET /crypto/salt).
 *
 * The derived key lives only in tab memory (see crypto/session.ts). It is never
 * persisted and never sent to the server. If the key is already present this
 * session, the gate renders its children immediately.
 *
 * NOTE: a wrong passphrase cannot be detected here — PBKDF2 always yields *a*
 * key. It is only caught on the first real decryption (GCM auth-tag mismatch),
 * where the reader surfaces "Incorrect passphrase — your data could not be
 * decrypted." This gate only fails fast on network/salt errors.
 */
export default function PassphraseGate({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(hasKey())
  const [salt, setSalt] = useState<Uint8Array | null>(null)
  const [passphrase, setPassphrase] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [loadingSalt, setLoadingSalt] = useState(!hasKey())

  useEffect(() => {
    if (ready) return
    let cancelled = false
    fetchSalt()
      .then((s) => {
        if (!cancelled) setSalt(s)
      })
      .catch(() => {
        if (!cancelled) setError('Could not reach the server to load your encryption salt.')
      })
      .finally(() => {
        if (!cancelled) setLoadingSalt(false)
      })
    return () => {
      cancelled = true
    }
  }, [ready])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!salt || !passphrase) return
    setBusy(true)
    setError(null)
    try {
      await initSession(passphrase, salt)
      setPassphrase('')
      setReady(true)
    } catch {
      setError('Could not derive a key from that passphrase. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  if (ready) return <>{children}</>

  return (
    <div className="flex h-screen w-screen items-center justify-center bg-theme-bg text-theme-text font-sans">
      <form
        onSubmit={handleSubmit}
        className="flex flex-col items-center gap-5 p-8 bg-theme-surface border border-theme-border rounded-2xl shadow-xl max-w-sm w-full mx-4"
      >
        <div className="flex flex-col items-center gap-2 select-none">
          <span className="text-2xl font-bold tracking-tight">Unlock your data</span>
          <span className="text-xs text-theme-text-muted text-center leading-relaxed">
            Your conversations are encrypted on your Drive. Enter your passphrase
            to decrypt them in this browser.
          </span>
        </div>

        <input
          type="password"
          autoFocus
          value={passphrase}
          onChange={(e) => setPassphrase(e.target.value)}
          placeholder="Passphrase"
          autoComplete="current-password"
          disabled={loadingSalt || busy}
          className="w-full px-4 py-2.5 rounded-xl text-sm bg-theme-bg border border-theme-border/60 text-theme-text placeholder-theme-text-muted focus:outline-none focus:border-theme-text-muted transition-colors disabled:opacity-60"
        />

        {error && (
          <p className="text-xs text-red-500 text-center bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg px-3 py-2 w-full">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy || loadingSalt || !passphrase}
          className="w-full px-5 py-2.5 bg-theme-brand text-theme-brand-text rounded-full shadow-sm hover:shadow-md active:scale-95 transition-all font-medium text-sm disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {loadingSalt ? 'Loading…' : busy ? 'Unlocking…' : 'Unlock'}
        </button>

        <p className="text-[11px] text-theme-text-muted text-center leading-relaxed opacity-70">
          There is no recovery — if you forget this passphrase, your encrypted
          data cannot be read. The passphrase never leaves this device.
        </p>
      </form>
    </div>
  )
}
