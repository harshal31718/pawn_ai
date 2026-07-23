import { useState, useRef, useEffect } from 'react'
import type { RegistryModel, ConversationMeta } from '../api/client'
import ApiKeysSection from './ApiKeysSection'
import ThemeToggle, { type Theme } from './ThemeToggle'

const BUBBLE_PRESETS = [
  { id: 'blue', label: 'Blue', bg: '#3b82f6', text: '#ffffff' },
  { id: 'indigo', label: 'Indigo', bg: '#4f46e5', text: '#ffffff' },
  { id: 'violet', label: 'Violet', bg: '#7c3aed', text: '#ffffff' },
  { id: 'teal', label: 'Teal', bg: '#0d9488', text: '#ffffff' },
  { id: 'emerald', label: 'Emerald', bg: '#059669', text: '#ffffff' },
  { id: 'rose', label: 'Rose', bg: '#e11d48', text: '#ffffff' },
  { id: 'amber', label: 'Amber', bg: '#d97706', text: '#ffffff' },
  { id: 'slate', label: 'Slate', bg: '#475569', text: '#ffffff' },
  { id: 'black', label: 'Black', bg: '#000000', text: '#ffffff' },
  { id: 'white', label: 'White', bg: '#ffffff', text: '#000000' },
]

interface Props {
  onClose: () => void
  isSidebarOpen?: boolean
  onOpenSidebar?: () => void
  theme: Theme
  onChangeTheme: (t: Theme) => void
  displayName: string
  onSaveDisplayName: (name: string) => void
  models: RegistryModel[]
  defaultModel: string
  onSaveDefaultModel: (id: string) => void
  onKeysChanged?: () => void
  userBubbleColor: string
  onChangeUserBubble: (id: string) => void
  aiBubbleColor: string
  onChangeAiBubble: (id: string) => void
  backgroundEffect: boolean
  onToggleBackgroundEffect: () => void
  conversations: ConversationMeta[]
  email: string
  onLogout: () => void
}

const SHORTCUTS = [
  { key: 'Enter', action: 'Send message' },
  { key: 'Shift + Enter', action: 'New line in message' },
  { key: 'Esc', action: 'Close settings / cancel rename' },
]

const FUTURE_ITEMS = [
  { label: 'Password & Authentication', desc: 'Password change, 2FA, login history, active sessions' },
  { label: 'Notifications', desc: 'Global toggle, message & system channels, quiet hours' },
  { label: 'Sync & Backup', desc: 'Cloud sync, data backup and restore across devices' },
  { label: 'Search Preferences', desc: 'Scope and filter defaults (search feature planned)' },
  { label: 'Startup Behavior', desc: 'Launch on login, open last chat (desktop app)' },
  { label: 'Security Alerts', desc: 'Notifications for suspicious account activity' },
]

const EXTRAS_ITEMS = [
  { label: 'Language & Region', desc: 'Display language, timezone, locale — UI is English-only, no i18n planned' },
  { label: 'Units', desc: 'Metric/Imperial — no measurements in a text chat app' },
  { label: 'Default View / Homepage', desc: 'Single-view app, no configuration needed' },
  { label: 'Vibrate & Notification Badges', desc: 'Mobile-only; not applicable to web' },
  { label: 'Profile Visibility', desc: 'Single-user app, no sharing or social features' },
  { label: 'Data Sharing & Activity Tracking', desc: 'No analytics infrastructure' },
  { label: 'Blocked Users & Parental Controls', desc: 'Single-user application' },
  { label: 'Media Quality, Auto-Play & Offline Mode', desc: 'Text-only chat — no media streaming' },
  { label: 'Game Controls / Key Bindings', desc: 'Not applicable' },
  { label: 'Billing & Subscriptions', desc: 'BYOK model — no subscription or payment' },
  { label: 'Workspace / Team Settings', desc: 'Single-user application' },
]

function BubbleColorRow({
  selectedId,
  onChange,
}: {
  selectedId: string
  onChange: (id: string) => void
}) {
  const scrollRef = useRef<HTMLDivElement>(null)

  function scroll() {
    if (scrollRef.current) {
      const { scrollLeft, scrollWidth, clientWidth } = scrollRef.current
      if (scrollLeft + clientWidth >= scrollWidth - 5) {
        scrollRef.current.scrollTo({ left: 0, behavior: 'smooth' })
      } else {
        scrollRef.current.scrollBy({ left: 80, behavior: 'smooth' })
      }
    }
  }

  return (
    <div className="flex-1 min-w-0 flex items-center gap-1.5">
      <div
        ref={scrollRef}
        className="flex-1 min-w-0 flex items-center gap-1.5 overflow-x-auto py-1 px-0.5 scroll-smooth"
        style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}
      >
        {BUBBLE_PRESETS.map((preset) => (
          <button
            key={preset.id} type="button"
            onClick={() => onChange(selectedId === preset.id ? '' : preset.id)}
            title={preset.label}
            className={`w-8 h-8 rounded-full border-2 transition-all shrink-0 ${selectedId === preset.id ? 'border-blue-500 scale-110 shadow-sm' : 'border-theme-border hover:border-theme-text-muted'
              }`}
            style={{ backgroundColor: preset.bg }}
          />
        ))}
      </div>
      <button
        type="button"
        onClick={scroll}
        className="w-8 h-8 flex items-center justify-center rounded-full bg-theme-bg border border-theme-border text-theme-text-muted hover:text-theme-text hover:bg-theme-surface-hover shrink-0 transition-colors focus:outline-none"
        title="Scroll colors"
      >
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor" className="w-3 h-3">
          <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
        </svg>
      </button>
    </div>
  )
}

export default function SettingsPage({
  onClose, isSidebarOpen, onOpenSidebar, theme, onChangeTheme,
  displayName, onSaveDisplayName,
  models, defaultModel, onSaveDefaultModel, onKeysChanged,
  userBubbleColor, onChangeUserBubble,
  aiBubbleColor, onChangeAiBubble,
  backgroundEffect, onToggleBackgroundEffect,
  conversations, email, onLogout,
}: Props) {
  const [nameInput, setNameInput] = useState(displayName)
  const [nameSaved, setNameSaved] = useState(false)
  const [clearConfirm, setClearConfirm] = useState(false)

  const nameSavedTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => { if (nameSavedTimer.current) clearTimeout(nameSavedTimer.current) }
  }, [])

  function handleSaveName() {
    const trimmed = nameInput.trim()
    if (!trimmed || trimmed === displayName) return
    onSaveDisplayName(trimmed)
    setNameSaved(true)
    if (nameSavedTimer.current) clearTimeout(nameSavedTimer.current)
    nameSavedTimer.current = setTimeout(() => setNameSaved(false), 2000)
  }

  const avatarLetter = displayName[0]?.toUpperCase() || 'U'

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden relative bg-theme-bg">

      {/* Floating Top Header */}
      <header className="absolute top-0 left-0 right-0 z-30 pointer-events-none p-4 flex items-center justify-between w-full">
        <div className="flex items-center gap-2 h-7 pl-2 pr-3 bg-theme-surface border border-theme-border/60 rounded-xl shadow-md pointer-events-auto z-20 transition-all">
          {/* Mobile-only reopen affordance -- "Back to chat" gets you to the
              sidebar indirectly (chat has its own hamburger), this makes it
              direct. Mirrors ChatPage.tsx's / ProvidersPage.tsx's toggle. */}
          {!isSidebarOpen && onOpenSidebar && (
            <button
              type="button"
              onClick={onOpenSidebar}
              className="md:hidden rounded-full text-theme-text-muted hover:bg-theme-bg/50 hover:text-theme-text transition-colors focus:outline-none flex items-center justify-center"
              title="Open sidebar"
            >
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
              </svg>
            </button>
          )}
          <button
            type="button" onClick={onClose}
            className="rounded-full text-theme-text-muted hover:bg-theme-bg/50 hover:text-theme-text transition-colors focus:outline-none flex items-center justify-center"
            title="Back to chat"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
            </svg>
          </button>
          <h1 className="text-xs font-semibold text-theme-text select-none">Settings</h1>
        </div>
      </header>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto pt-14 px-4 pb-10">
        <div className="w-full max-w-6xl mx-auto py-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 items-start">

            {/* Left Column */}
            <div className="space-y-6">
              {/* ── Appearance ── */}
              <section>
                <h2 className="text-[10px] font-semibold uppercase tracking-widest text-theme-text-muted mb-3">Appearance</h2>
                <div className="bg-theme-surface border border-theme-border/50 rounded-xl divide-y divide-theme-border/30">

                  {/* Theme */}
                  <div className="p-3 space-y-2">
                    <p className="text-xs font-medium text-theme-text">Theme</p>
                    <ThemeToggle theme={theme} onChangeTheme={onChangeTheme} variant="detailed" />
                  </div>

                  {/* Background effect toggle */}
                  <div className="flex items-center justify-between p-3">
                    <div>
                      <p className="text-xs font-medium text-theme-text">Background effect</p>
                    </div>
                    <button
                      type="button"
                      onClick={onToggleBackgroundEffect}
                      className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none ${backgroundEffect ? 'bg-blue-500' : 'bg-theme-border'
                        }`}
                      role="switch"
                      aria-checked={backgroundEffect}
                    >
                      <span className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow-sm transform transition-transform duration-200 ${backgroundEffect ? 'translate-x-4' : 'translate-x-0'
                        }`} />
                    </button>
                  </div>

                  {/* User bubble color */}
                  <div className="flex items-center justify-between p-3 gap-3">
                    <div className="w-24 shrink-0 text-xs font-medium text-theme-text">User messages</div>
                    <BubbleColorRow selectedId={userBubbleColor} onChange={onChangeUserBubble} />
                  </div>

                  {/* AI bubble color */}
                  <div className="flex items-center justify-between p-3 gap-3">
                    <div className="w-24 shrink-0 text-xs font-medium text-theme-text">AI messages</div>
                    <BubbleColorRow selectedId={aiBubbleColor} onChange={onChangeAiBubble} />
                  </div>

                </div>
              </section>

              {/* ── Keyboard Shortcuts ── */}
              <section>
                <h2 className="text-[10px] font-semibold uppercase tracking-widest text-theme-text-muted mb-3">Keyboard Shortcuts</h2>
                <div className="bg-theme-surface border border-theme-border/50 rounded-xl divide-y divide-theme-border/30">
                  {SHORTCUTS.map(({ key, action }) => (
                    <div key={key} className="flex items-center justify-between px-3 py-2">
                      <span className="text-xs text-theme-text-muted">{action}</span>
                      <kbd className="text-[10px] font-mono bg-theme-bg border border-theme-border/60 text-theme-text px-2 py-0.5 rounded-md select-none">
                        {key}
                      </kbd>
                    </div>
                  ))}
                </div>
              </section>

              {/* ── Future ── */}
              <section>
                <h2 className="text-[10px] font-semibold uppercase tracking-widest text-theme-text-muted mb-3">Future</h2>
                <div className="bg-theme-surface border border-theme-border/50 rounded-xl divide-y divide-theme-border/30">
                  {FUTURE_ITEMS.map(({ label, desc }) => (
                    <div key={label} className="px-3 py-2 opacity-50 select-none pointer-events-none">
                      <p className="text-xs font-medium text-theme-text">{label}</p>
                      <p className="text-[10px] text-theme-text-muted mt-0.5">{desc}</p>
                    </div>
                  ))}
                </div>
              </section>
            </div>

            {/* Middle Column */}
            <div className="space-y-6">
              {/* ── Chat Defaults ── */}
              <section>
                <h2 className="text-[10px] font-semibold uppercase tracking-widest text-theme-text-muted mb-3">Chat Defaults</h2>
                <div className="bg-theme-surface border border-theme-border/50 rounded-xl p-3">
                  <div className="space-y-2">
                    <label className="text-xs font-medium text-theme-text block">Default model</label>
                    <select
                      value={defaultModel}
                      onChange={(e) => onSaveDefaultModel(e.target.value)}
                      className="text-xs bg-theme-bg border border-theme-border rounded-lg px-2.5 py-1.5 text-theme-text focus:outline-none focus:ring-1 focus:ring-theme-brand/50 cursor-pointer w-full"
                    >
                      {models.map((m) => (
                        <option key={m.model_id} value={m.model_id}>{m.display_name}</option>
                      ))}
                      {models.length === 0 && <option value={defaultModel}>{defaultModel}</option>}
                    </select>
                  </div>
                </div>
              </section>

              {/* ── API Keys (BYOK) ── */}
              <ApiKeysSection onKeysChanged={onKeysChanged} />
            </div>

            {/* Right Column */}
            <div className="space-y-6">
              {/* ── Profile ── */}
              <section>
                <h2 className="text-[10px] font-semibold uppercase tracking-widest text-theme-text-muted mb-3">Profile</h2>
                <div className="bg-theme-surface border border-theme-border/50 rounded-xl p-3 space-y-3">
                  {/* Row 1: Display Name */}
                  <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-full bg-theme-brand text-theme-brand-text flex items-center justify-center font-bold text-sm shrink-0 select-none">
                      {avatarLetter}
                    </div>
                    <div className="flex-1 min-w-0">
                      <label className="text-[10px] font-medium text-theme-text-muted block mb-1">Display name</label>
                      <div className="flex flex-col sm:flex-row md:flex-col xl:flex-row gap-2">
                        <input
                          type="text" value={nameInput}
                          onChange={(e) => { setNameInput(e.target.value); setNameSaved(false) }}
                          onKeyDown={(e) => e.key === 'Enter' && handleSaveName()}
                          placeholder="Your name"
                          className="flex-1 min-w-0 bg-theme-bg border border-theme-border rounded-lg px-3 py-1.5 text-xs text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-brand/50"
                        />
                        <button
                          type="button" onClick={handleSaveName}
                          disabled={!nameInput.trim() || nameInput.trim() === displayName}
                          className="px-3 py-1.5 text-xs bg-theme-brand text-theme-brand-text rounded-lg hover:opacity-90 transition-opacity font-semibold disabled:opacity-40 disabled:cursor-not-allowed shrink-0 w-full sm:w-auto md:w-full xl:w-auto text-center cursor-pointer"
                        >
                          {nameSaved ? 'Saved' : 'Save'}
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* Row 2: Email & Sign out */}
                  <div className="flex flex-col sm:flex-row md:flex-col xl:flex-row items-stretch sm:items-end md:items-stretch xl:items-end gap-2 pt-1">
                    <div className="flex-1 min-w-0">
                      <label className="text-[10px] font-medium text-theme-text-muted block mb-1">Email</label>
                      <p className="text-xs text-theme-text-muted px-3 py-1.5 bg-theme-bg border border-theme-border/50 rounded-lg opacity-60 select-none truncate" title={email || 'Not signed in'}>
                        {email || 'Not signed in'}
                      </p>
                    </div>
                    <button
                      type="button" onClick={onLogout}
                      className="text-xs px-3 py-1.5 bg-theme-bg border border-red-500/40 rounded-lg text-red-500 hover:bg-red-500/10 transition-colors font-semibold shrink-0 w-full sm:w-auto md:w-full xl:w-auto text-center cursor-pointer"
                    >
                      Sign out
                    </button>
                  </div>

                  {/* Row 3: Data actions */}
                  <div className="pt-2 border-t border-theme-border/20">
                    {clearConfirm ? (
                      <div className="flex items-center gap-1.5">
                        <span className="text-[10px] text-theme-text-muted select-none">Sure?</span>
                        <button
                          type="button" onClick={() => setClearConfirm(false)}
                          className="text-[10px] px-2 py-1 border border-theme-border rounded-md text-theme-text-muted hover:bg-theme-surface-hover transition-colors cursor-pointer"
                        >No</button>
                        <button
                          type="button"
                          onClick={() => setClearConfirm(false)}
                          disabled
                          className="text-[10px] px-2 py-1 bg-red-600 text-white rounded-md hover:bg-red-700 transition-colors font-semibold cursor-not-allowed opacity-50"
                        >Yes, delete</button>
                      </div>
                    ) : (
                      <button
                        type="button" onClick={() => setClearConfirm(true)}
                        disabled={conversations.length === 0}
                        className="text-[11px] px-2.5 py-1.5 bg-theme-bg border border-red-500/40 rounded-lg text-red-500 hover:bg-red-500/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed font-semibold cursor-pointer"
                      >
                        Clear Data
                      </button>
                    )}
                  </div>
                </div>
              </section>

              {/* ── Extras ── */}
              <section>
                <h2 className="text-[10px] font-semibold uppercase tracking-widest text-theme-text-muted mb-3">Extras</h2>
                <div className="bg-theme-surface border border-theme-border/50 rounded-xl divide-y divide-theme-border/30">
                  {EXTRAS_ITEMS.map(({ label, desc }) => (
                    <div key={label} className="px-3 py-2 opacity-40 select-none pointer-events-none">
                      <p className="text-xs font-medium text-theme-text">{label}</p>
                      <p className="text-[10px] text-theme-text-muted mt-0.5">{desc}</p>
                    </div>
                  ))}
                </div>
              </section>
            </div>

          </div>
        </div>
      </div>
    </div>
  )
}
