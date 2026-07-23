import { useState } from 'react'
import { changePassword } from '../api/client'
import { useAuth } from '../contexts/AuthContext'

function PasswordField({
  value,
  onChange,
  placeholder,
  autoComplete,
}: {
  value: string
  onChange: (v: string) => void
  placeholder: string
  autoComplete: string
}) {
  const [show, setShow] = useState(false)
  return (
    <div className="relative">
      <input
        type={show ? 'text' : 'password'}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete={autoComplete}
        className="w-full text-xs bg-theme-bg border border-theme-border rounded-lg px-3 py-1.5 pr-9 text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-brand/50"
      />
      <button
        type="button"
        onClick={() => setShow((s) => !s)}
        className="absolute right-2 top-1/2 -translate-y-1/2 text-theme-text-muted hover:text-theme-text transition-colors cursor-pointer"
        title={show ? 'Hide' : 'Show'}
      >
        {show ? (
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-3.5 h-3.5">
            <path strokeLinecap="round" strokeLinejoin="round" d="M3.98 8.223A10.477 10.477 0 001.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.451 10.451 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.522 10.522 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.242 4.242L9.88 9.88" />
          </svg>
        ) : (
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-3.5 h-3.5">
            <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        )}
      </button>
    </div>
  )
}

const MIN_PASSWORD_LENGTH = 8

/** Login-change plan (2026-07-23): Settings → Change Password. Own file,
 *  mirroring how ApiKeysSection.tsx is already split out. No current-password
 *  field -- the backend no longer asks for it (the active session is the
 *  auth), so this doubles as both "change" and "forgot" from within
 *  Settings. Client-side validation mirrors the backend (new === confirm,
 *  length >= 8) before the round-trip; on success also patches AuthContext's
 *  user state so PasswordNudgeModal doesn't reappear before the next full
 *  reload. */
export default function ChangePasswordSection() {
  const { updateUser } = useAuth()
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  async function handleSave() {
    setError(null)
    if (next !== confirm) {
      setError('New password and confirmation do not match.')
      return
    }
    if (next.length < MIN_PASSWORD_LENGTH) {
      setError(`New password must be at least ${MIN_PASSWORD_LENGTH} characters.`)
      return
    }
    setBusy(true)
    try {
      await changePassword(next)
      setNext('')
      setConfirm('')
      updateUser({ password_changed: true })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to change password.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-2">
      <PasswordField
        value={next}
        onChange={setNext}
        placeholder="New password"
        autoComplete="new-password"
      />
      <PasswordField
        value={confirm}
        onChange={setConfirm}
        placeholder="Confirm new password"
        autoComplete="new-password"
      />
      {error && <p className="text-[10px] text-red-500">{error}</p>}
      <button
        type="button"
        onClick={handleSave}
        disabled={busy || !next || !confirm}
        className="w-full text-xs px-3 py-1.5 bg-theme-brand text-theme-brand-text rounded-lg hover:opacity-90 transition-opacity font-semibold disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
      >
        {saved ? 'Saved' : busy ? 'Saving…' : 'Change Password'}
      </button>
    </div>
  )
}
