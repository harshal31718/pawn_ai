import { useState } from 'react'
import { useAuth } from '../contexts/AuthContext'

export default function LoginPage() {
  const { login } = useAuth()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleLogin() {
    setLoading(true)
    setError(null)
    try {
      await login()
    } catch {
      setError('Could not reach the auth server. Make sure the backend is running.')
      setLoading(false)
    }
  }

  return (
    <div className="flex h-screen w-screen items-center justify-center bg-theme-bg text-theme-text font-sans">
      <div className="flex flex-col items-center gap-6 p-8 bg-theme-surface border border-theme-border rounded-2xl shadow-xl max-w-sm w-full mx-4">
        {/* Logo / Title */}
        <div className="flex flex-col items-center gap-2 select-none">
          <span className="text-3xl font-bold tracking-tight">PAWN</span>
          <span className="text-xs text-theme-text-muted uppercase tracking-widest">Personal AI Workspace</span>
        </div>

        <p className="text-sm text-theme-text-muted text-center leading-relaxed">
          Sign in with Google to access your conversations and AI tools. Your data stays on your own Drive.
        </p>

        {error && (
          <p className="text-xs text-red-500 text-center bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg px-3 py-2">
            {error}
          </p>
        )}

        <button
          onClick={handleLogin}
          disabled={loading}
          className="flex items-center gap-3 px-5 py-2.5 bg-white text-gray-700 border border-gray-200 rounded-full shadow-sm hover:shadow-md active:scale-95 transition-all font-medium text-sm disabled:opacity-60 disabled:cursor-not-allowed w-full justify-center"
        >
          {/* Google G logo (inline SVG) */}
          <svg viewBox="0 0 48 48" className="w-5 h-5 shrink-0">
            <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
            <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
            <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
            <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
            <path fill="none" d="M0 0h48v48H0z"/>
          </svg>
          {loading ? 'Redirecting…' : 'Sign in with Google'}
        </button>

        <p className="text-[11px] text-theme-text-muted text-center leading-relaxed opacity-70">
          By signing in, you grant PAWN access to create files in your Google Drive.
        </p>
      </div>
    </div>
  )
}
