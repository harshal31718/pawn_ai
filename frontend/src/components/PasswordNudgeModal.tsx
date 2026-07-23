import { useNavigate } from 'react-router-dom'

/** Login-change plan (2026-07-23): one-time-per-login nudge to replace the
 *  auto-generated password. Layout.tsx mounts this and controls visibility
 *  via `user.password_changed` (server-side source of truth) -- no
 *  localStorage flag, since it must persist across logins, not just this
 *  client session. */
export default function PasswordNudgeModal({ onDismiss }: { onDismiss: () => void }) {
  const navigate = useNavigate()

  function handleChangeNow() {
    onDismiss()
    navigate('/settings')
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-sm bg-theme-surface border border-theme-border rounded-xl p-5 space-y-4 shadow-xl">
        <div>
          <h2 className="text-sm font-semibold text-theme-text">Set your own password</h2>
          <p className="mt-1.5 text-xs text-theme-text-muted leading-relaxed">
            You're still using the password we generated for you at signup. Change it to one
            of your own choosing whenever you're ready — you can do this any time from
            Settings.
          </p>
        </div>

        <div className="flex gap-2">
          <button
            type="button"
            onClick={onDismiss}
            className="flex-1 text-xs px-3 py-1.5 bg-theme-bg border border-theme-border rounded-lg text-theme-text-muted hover:text-theme-text transition-colors font-semibold cursor-pointer"
          >
            Remind me later
          </button>
          <button
            type="button"
            onClick={handleChangeNow}
            className="flex-1 text-xs px-3 py-1.5 bg-theme-brand text-theme-brand-text rounded-lg hover:opacity-90 transition-opacity font-semibold cursor-pointer"
          >
            Change password now
          </button>
        </div>
      </div>
    </div>
  )
}
