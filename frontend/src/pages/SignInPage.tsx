import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useThemePreference } from '../hooks/useThemePreference'
import InteractiveGridBackground from '../components/InteractiveGridBackground'
import ThemeToggle from '../components/ThemeToggle'
import GoogleSignInButton from '../components/GoogleSignInButton'

/** Login-change plan (2026-07-23): Sign In page -- Google (same button/flow
 *  as LandingPage's Sign Up, since Google doesn't distinguish the two) OR
 *  email+password for a returning user. Same chrome as LandingPage
 *  (InteractiveGridBackground, ThemeToggle, /privacy footer link) so the two
 *  read as one consistent auth experience, not two different apps. */
export default function SignInPage() {
  const { login, loginWithPassword } = useAuth()
  const { theme, setTheme, isDark } = useThemePreference()
  const [googleLoading, setGoogleLoading] = useState(false)
  const [googleError, setGoogleError] = useState<string | null>(null)

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [passwordLoading, setPasswordLoading] = useState(false)
  const [passwordError, setPasswordError] = useState<string | null>(null)

  async function handleGoogleLogin() {
    setGoogleLoading(true)
    setGoogleError(null)
    try {
      await login()
    } catch {
      setGoogleError('Could not reach the auth server. Make sure the backend is running.')
      setGoogleLoading(false)
    }
  }

  async function handlePasswordLogin(e: React.FormEvent) {
    e.preventDefault()
    setPasswordLoading(true)
    setPasswordError(null)
    try {
      await loginWithPassword(email.trim(), password)
    } catch (err) {
      setPasswordError(err instanceof Error ? err.message : 'Sign in failed')
    } finally {
      setPasswordLoading(false)
    }
  }

  return (
    <div className="relative min-h-screen w-screen bg-theme-bg text-theme-text font-sans overflow-x-hidden">
      <InteractiveGridBackground darkMode={isDark} speedMultiplier={3} />

      <header className="absolute top-0 inset-x-0 z-20 flex items-center justify-between px-5 sm:px-8 py-5">
        <div className="flex items-center gap-2.5 select-none">
          <span className="font-[family-name:var(--font-display)] text-lg font-semibold tracking-tight">PAWN</span>
          <span className="font-[family-name:var(--font-accent-mono)] text-[9px] uppercase tracking-[0.15em] text-theme-text-muted border border-theme-border rounded-full px-2 py-0.5">
            Beta
          </span>
        </div>
        <ThemeToggle theme={theme} onChangeTheme={setTheme} variant="compact" />
      </header>

      <section className="relative z-10 flex flex-col items-center justify-center px-6 pt-32 pb-20 sm:pt-40 min-h-screen text-center">
        <div className="animate-in fade-in slide-in-from-bottom-4 duration-700">
          <span className="font-[family-name:var(--font-accent-mono)] text-[10px] uppercase tracking-[0.2em] text-theme-text-muted">
            Welcome back
          </span>
        </div>

        <h1 className="mt-4 font-[family-name:var(--font-display)] font-bold tracking-tight text-4xl sm:text-5xl animate-in fade-in slide-in-from-bottom-6 duration-700 delay-100 [animation-fill-mode:backwards]">
          Sign in
        </h1>

        <div className="mt-9 flex flex-col items-center gap-3 w-full max-w-xs animate-in fade-in slide-in-from-bottom-6 duration-700 delay-200 [animation-fill-mode:backwards]">
          <div className="w-64">
            <GoogleSignInButton onClick={handleGoogleLogin} loading={googleLoading} />
          </div>

          {googleError && (
            <p className="text-xs text-red-500 text-center bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg px-3 py-2 max-w-xs">
              {googleError}
            </p>
          )}

          <div className="flex items-center gap-3 w-full my-1">
            <div className="flex-1 h-px bg-theme-border" />
            <span className="text-[10px] uppercase tracking-widest text-theme-text-muted">or</span>
            <div className="flex-1 h-px bg-theme-border" />
          </div>

          <form onSubmit={handlePasswordLogin} className="w-full flex flex-col gap-2.5 text-left">
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="Email"
              className="w-full text-sm bg-theme-surface border border-theme-border rounded-lg px-3 py-2 text-theme-text placeholder:text-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-brand"
            />
            <div className="relative">
              <input
                type={showPassword ? 'text' : 'password'}
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Password"
                className="w-full text-sm bg-theme-surface border border-theme-border rounded-lg px-3 py-2 pr-10 text-theme-text placeholder:text-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-brand"
              />
              <button
                type="button"
                onClick={() => setShowPassword((s) => !s)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-theme-text-muted hover:text-theme-text transition-colors"
                title={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? (
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M3.98 8.223A10.477 10.477 0 001.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.451 10.451 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.522 10.522 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.242 4.242L9.88 9.88" />
                  </svg>
                ) : (
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  </svg>
                )}
              </button>
            </div>
            <button
              type="submit"
              disabled={passwordLoading}
              className="w-full text-sm font-medium bg-theme-brand text-white rounded-lg px-3 py-2 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer transition-opacity"
            >
              {passwordLoading ? 'Signing in…' : 'Sign in'}
            </button>
          </form>

          {passwordError && (
            <p className="text-xs text-red-500 text-center bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg px-3 py-2 w-full">
              {passwordError}
            </p>
          )}

          <Link
            to="/"
            className="mt-3 text-[11px] text-theme-text-muted underline underline-offset-2 hover:text-theme-text transition-colors"
          >
            New here? Create an account
          </Link>
        </div>
      </section>

      <footer className="absolute bottom-0 inset-x-0 z-10 px-6 pb-10 text-center">
        <Link
          to="/privacy"
          className="text-[11px] text-theme-text-muted underline underline-offset-2 hover:text-theme-text transition-colors"
        >
          Privacy Policy
        </Link>
      </footer>
    </div>
  )
}
