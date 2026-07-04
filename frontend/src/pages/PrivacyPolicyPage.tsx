import { Link } from 'react-router-dom'

const SECTIONS: { title: string; body: React.ReactNode }[] = [
  {
    title: 'What we collect',
    body: (
      <>
        When you sign in with Google, PAWN receives your name, email address, and profile
        picture. This is used solely to identify your account — PAWN never sees your Google
        password.
      </>
    ),
  },
  {
    title: 'Google Drive access',
    body: (
      <>
        PAWN requests Google's restricted <code className="font-[family-name:var(--font-accent-mono)] text-[13px] bg-theme-bg border border-theme-border rounded px-1 py-0.5">drive.file</code> scope,
        which only grants access to files PAWN itself creates in your Drive — your conversation
        history and any files you upload inside PAWN. PAWN cannot see, list, or read any file
        that already existed in your Drive; this is a technical limitation of the scope, not
        just a policy promise.
      </>
    ),
  },
  {
    title: 'Where your data lives',
    body: (
      <>
        Your conversations and uploads are stored in <strong>your own Google Drive</strong>,
        not on PAWN's servers. PAWN's own database (a self-hosted PostgreSQL instance) stores
        only your account record, your encrypted provider API keys (if you use "bring your own
        key"), and your encrypted Drive access tokens.
      </>
    ),
  },
  {
    title: 'Encryption',
    body: (
      <>
        API keys and Drive tokens are encrypted at rest with AES-256-GCM before being written
        to the database. They are never returned by any PAWN API response.
      </>
    ),
  },
  {
    title: 'Third parties',
    body: (
      <>
        Your data is never sold or shared with third parties. Messages you send are relayed
        only to the LLM provider you selected (e.g. Gemini, Groq) in order to generate a reply
        — using either your own API key, or a shared fallback key if one is configured.
      </>
    ),
  },
  {
    title: 'Data deletion',
    body: (
      <>
        You can revoke PAWN's access at any time from your{' '}
        <a
          href="https://myaccount.google.com/permissions"
          target="_blank"
          rel="noreferrer"
          className="underline underline-offset-2 hover:text-theme-text"
        >
          Google Account permissions page
        </a>
        . Contact us (below) to request deletion of your PAWN account record.
      </>
    ),
  },
  {
    title: 'Changes to this policy',
    body: <>Any changes to this policy will be reflected on this page with an updated date.</>,
  },
  {
    title: 'Contact',
    body: (
      <>
        Questions about this policy or your data — reach out at{' '}
        <a href="mailto:hello@example.com" className="underline underline-offset-2 hover:text-theme-text">
          hello@example.com
        </a>
        .
      </>
    ),
  },
]

export default function PrivacyPolicyPage() {
  return (
    <div className="min-h-screen w-screen bg-theme-bg text-theme-text font-sans">
      <div className="max-w-2xl mx-auto px-6 py-14">
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 text-xs text-theme-text-muted hover:text-theme-text transition-colors mb-8"
        >
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" className="w-3.5 h-3.5">
            <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
          </svg>
          Back to PAWN
        </Link>

        <h1 className="font-[family-name:var(--font-display)] text-3xl sm:text-4xl font-bold tracking-tight">
          Privacy Policy
        </h1>
        <p className="mt-2 text-xs text-theme-text-muted">Last updated: July 2026</p>

        <div className="mt-10 bg-theme-surface border border-theme-border rounded-2xl divide-y divide-theme-border">
          {SECTIONS.map((s) => (
            <div key={s.title} className="p-6">
              <h2 className="font-[family-name:var(--font-accent-mono)] text-[11px] uppercase tracking-[0.12em] text-theme-text-muted mb-2">
                {s.title}
              </h2>
              <p className="text-sm leading-relaxed text-theme-text">{s.body}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
