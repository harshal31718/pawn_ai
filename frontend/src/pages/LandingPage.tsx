import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useThemePreference } from '../hooks/useThemePreference'
import InteractiveGridBackground from '../components/InteractiveGridBackground'
import ThemeToggle from '../components/ThemeToggle'
import GoogleSignInButton from '../components/GoogleSignInButton'

const FEATURES = [
  {
    eyebrow: 'Chat',
    title: 'Bring your own key, bring your own limits.',
    body: 'Chat across six providers — Gemini, Groq, Cerebras, HuggingFace, GitHub Models, OpenRouter — using your own API keys, with transparent rate-limit failover when one is momentarily throttled.',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-5 h-5">
        <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 01-2.555-.337A5.972 5.972 0 015.41 20.97a5.969 5.969 0 01-.474-.065 4.48 4.48 0 00.978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z" />
      </svg>
    ),
    status: 'live' as const,
  },
  {
    eyebrow: 'Image Lab',
    title: 'Generate images without paying for an API.',
    body: 'SDXL and FLUX.1-schnell running on your own free Kaggle GPU quota. Connect a Kaggle account once — no image-generation API key required, ever.',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-5 h-5">
        <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 001.5-1.5V6a1.5 1.5 0 00-1.5-1.5H3.75A1.5 1.5 0 002.25 6v12a1.5 1.5 0 001.5 1.5zm10.5-11.25h.008v.008h-.008V8.25zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" />
      </svg>
    ),
    status: 'live' as const,
  },
  {
    eyebrow: 'Video',
    title: 'Video generation — coming soon.',
    body: "Text-to-video is next on the list, using the same bring-your-own-quota philosophy as everything else in PAWN.",
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-5 h-5">
        <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 10.5l4.72-4.72a.75.75 0 011.28.53v11.38a.75.75 0 01-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 002.25-2.25v-9a2.25 2.25 0 00-2.25-2.25h-9A2.25 2.25 0 002.25 7.5v9a2.25 2.25 0 002.25 2.25z" />
      </svg>
    ),
    status: 'soon' as const,
  },
]

export default function LandingPage() {
  const { login } = useAuth()
  const { theme, setTheme, isDark } = useThemePreference()
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
    <div className="relative min-h-screen w-screen bg-theme-bg text-theme-text font-sans overflow-x-hidden">
      <InteractiveGridBackground darkMode={isDark} speedMultiplier={3} />

      {/* Top bar */}
      <header className="absolute top-0 inset-x-0 z-20 flex items-center justify-between px-5 sm:px-8 py-5">
        <div className="flex items-center gap-2.5 select-none">
          <span className="font-[family-name:var(--font-display)] text-lg font-semibold tracking-tight">PAWN</span>
          <span className="font-[family-name:var(--font-accent-mono)] text-[9px] uppercase tracking-[0.15em] text-theme-text-muted border border-theme-border rounded-full px-2 py-0.5">
            Beta
          </span>
        </div>
        <ThemeToggle theme={theme} onChangeTheme={setTheme} variant="compact" />
      </header>

      {/* Hero */}
      <section className="relative z-10 flex flex-col items-center justify-center px-6 pt-32 pb-20 sm:pt-40 sm:pb-28 text-center">
        <div className="animate-in fade-in slide-in-from-bottom-4 duration-700">
          <span className="font-[family-name:var(--font-accent-mono)] text-[10px] uppercase tracking-[0.2em] text-theme-text-muted">
            Personal AI Workspace
          </span>
        </div>

        <h1 className="mt-4 font-[family-name:var(--font-display)] font-bold tracking-tight text-6xl sm:text-7xl md:text-8xl animate-in fade-in slide-in-from-bottom-6 duration-700 delay-100 [animation-fill-mode:backwards]">
          PAWN
        </h1>

        <p className="mt-6 max-w-xl text-base sm:text-lg text-theme-text-muted leading-relaxed animate-in fade-in slide-in-from-bottom-6 duration-700 delay-200 [animation-fill-mode:backwards]">
          One workspace, every model — chat on your own API keys, generate images on
          free GPU credits, no limits PAWN imposes on you.
        </p>

        <div className="mt-9 flex flex-col items-center gap-3 animate-in fade-in slide-in-from-bottom-6 duration-700 delay-300 [animation-fill-mode:backwards]">
          <div className="w-64">
            <GoogleSignInButton onClick={handleLogin} loading={loading} />
          </div>

          {error && (
            <p className="text-xs text-red-500 text-center bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg px-3 py-2 max-w-xs">
              {error}
            </p>
          )}

          <p className="text-[11px] text-theme-text-muted max-w-xs leading-relaxed">
            Your data stays on your own Google Drive.
          </p>

          <p className="mt-2 text-[11px] text-theme-text-muted/80 max-w-sm leading-relaxed border-t border-theme-border pt-3">
            PAWN is an independent BETA project, not yet verified by Google — you may see a
            "Google hasn't verified this app" screen during sign-in. That's expected; click{' '}
            <span className="font-medium text-theme-text-muted">Advanced → Go to PAWN</span> to continue.
          </p>

          <Link
            to="/login"
            className="text-[11px] text-theme-text-muted underline underline-offset-2 hover:text-theme-text transition-colors"
          >
            Already have an account? Sign in
          </Link>
        </div>
      </section>

      {/* Feature highlights */}
      <section className="relative z-10 px-6 pb-16 sm:pb-20">
        <div className="max-w-5xl mx-auto grid grid-cols-1 md:grid-cols-3 gap-5">
          {FEATURES.map((f, i) => (
            <div
              key={f.title}
              className={`group relative flex flex-col gap-4 rounded-2xl border p-6 text-left transition-colors animate-in fade-in slide-in-from-bottom-4 duration-700 [animation-fill-mode:backwards] ${
                f.status === 'soon'
                  ? 'border-dashed border-theme-border/70 bg-theme-surface/40 opacity-75'
                  : 'border-theme-border bg-theme-surface hover:border-theme-text-muted/50'
              }`}
              style={{ animationDelay: `${400 + i * 120}ms` }}
            >
              <div className="flex items-center justify-between">
                <span className="font-[family-name:var(--font-accent-mono)] text-[10px] uppercase tracking-[0.15em] text-theme-text-muted">
                  {f.eyebrow}
                </span>
                {f.status === 'soon' ? (
                  <span className="font-[family-name:var(--font-accent-mono)] text-[9px] uppercase tracking-widest text-theme-text-muted border border-dashed border-theme-border rounded-full px-2 py-0.5">
                    Roadmap
                  </span>
                ) : (
                  <span className="w-1.5 h-1.5 rounded-full bg-theme-text-muted/40 group-hover:bg-theme-text transition-colors" />
                )}
              </div>

              <div className="w-9 h-9 rounded-lg bg-theme-bg border border-theme-border flex items-center justify-center text-theme-text">
                {f.icon}
              </div>

              <h3 className="font-[family-name:var(--font-display)] text-lg font-semibold leading-snug">
                {f.title}
              </h3>
              <p className="text-sm text-theme-text-muted leading-relaxed">{f.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Footer */}
      <footer className="relative z-10 px-6 pb-10 text-center">
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
