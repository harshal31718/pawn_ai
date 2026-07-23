import { useState } from 'react'
import { useAuth } from '../contexts/AuthContext'

/** Login-change plan (2026-07-23): one-time reveal of the auto-generated
 *  password immediately after a fresh Google signup. Renders nothing when
 *  `generatedPassword` is null (every other case: re-logins, password
 *  logins, and any render after "Done" is clicked). */
export default function GeneratedPasswordModal() {
  const { generatedPassword, clearGeneratedPassword } = useAuth()
  const [copied, setCopied] = useState(false)

  if (!generatedPassword) return null

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(generatedPassword!)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard API unavailable/denied — the field is still selectable by hand.
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-sm bg-theme-surface border border-theme-border rounded-xl p-5 space-y-4 shadow-xl">
        <div>
          <h2 className="text-sm font-semibold text-theme-text">Your account password</h2>
          <p className="mt-1.5 text-xs text-theme-text-muted leading-relaxed">
            We generated a password for your account so you can sign in without Google next
            time. Save it now — you can change it later in Settings, but this is the only time
            it's shown.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <input
            type="text"
            readOnly
            value={generatedPassword}
            onFocus={(e) => e.target.select()}
            className="flex-1 min-w-0 text-sm font-mono bg-theme-bg border border-theme-border rounded-lg px-3 py-1.5 text-theme-text select-all"
          />
          <button
            type="button"
            onClick={handleCopy}
            className="text-xs px-3 py-1.5 bg-theme-bg border border-theme-border rounded-lg text-theme-text-muted hover:text-theme-text transition-colors font-semibold shrink-0 cursor-pointer"
          >
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>

        <button
          type="button"
          onClick={clearGeneratedPassword}
          className="w-full text-xs px-3 py-1.5 bg-theme-brand text-theme-brand-text rounded-lg hover:opacity-90 transition-opacity font-semibold cursor-pointer"
        >
          Done
        </button>
      </div>
    </div>
  )
}
