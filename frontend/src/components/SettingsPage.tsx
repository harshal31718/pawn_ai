import { useState } from 'react'
import type { RegistryModel, ConversationMeta } from '../api/client'
import ApiKeysSection from './ApiKeysSection'

type Theme = 'system' | 'light' | 'dark'

const BUBBLE_PRESETS = [
  { id: 'blue',    label: 'Blue',    bg: '#3b82f6', text: '#ffffff' },
  { id: 'indigo',  label: 'Indigo',  bg: '#4f46e5', text: '#ffffff' },
  { id: 'violet',  label: 'Violet',  bg: '#7c3aed', text: '#ffffff' },
  { id: 'teal',    label: 'Teal',    bg: '#0d9488', text: '#ffffff' },
  { id: 'emerald', label: 'Emerald', bg: '#059669', text: '#ffffff' },
  { id: 'rose',    label: 'Rose',    bg: '#e11d48', text: '#ffffff' },
  { id: 'amber',   label: 'Amber',   bg: '#d97706', text: '#ffffff' },
  { id: 'slate',   label: 'Slate',   bg: '#475569', text: '#ffffff' },
  { id: 'black',   label: 'Black',   bg: '#000000', text: '#ffffff' },
  { id: 'white',   label: 'White',   bg: '#ffffff', text: '#000000' },
]

interface Props {
  onClose: () => void
  theme: Theme
  onChangeTheme: (t: Theme) => void
  isDark: boolean
  displayName: string
  onSaveDisplayName: (name: string) => void
  models: RegistryModel[]
  defaultModel: string
  onSaveDefaultModel: (id: string) => void
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

export default function SettingsPage({
  onClose, theme, onChangeTheme, isDark,
  displayName, onSaveDisplayName,
  models, defaultModel, onSaveDefaultModel,
  userBubbleColor, onChangeUserBubble,
  aiBubbleColor, onChangeAiBubble,
  backgroundEffect, onToggleBackgroundEffect,
  conversations, email, onLogout,
}: Props) {
  const [nameInput, setNameInput] = useState(displayName)
  const [nameSaved, setNameSaved] = useState(false)
  const [clearConfirm, setClearConfirm] = useState(false)

  function handleSaveName() {
    const trimmed = nameInput.trim()
    if (!trimmed || trimmed === displayName) return
    onSaveDisplayName(trimmed)
    setNameSaved(true)
    setTimeout(() => setNameSaved(false), 2000)
  }

  function handleExport() {
    const blob = new Blob([JSON.stringify(conversations, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'pawn-conversations.json'
    a.click()
    URL.revokeObjectURL(url)
  }

  const avatarLetter = nameInput.trim()[0]?.toUpperCase() || displayName[0]?.toUpperCase() || 'U'
  const themeOptions: { value: Theme; label: string }[] = [
    { value: 'system', label: 'System' },
    { value: 'light',  label: 'Light'  },
    { value: 'dark',   label: 'Dark'   },
  ]

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden relative bg-theme-bg">

      {/* Floating Top Header */}
      <header className="absolute top-0 left-0 right-0 z-30 pointer-events-none p-4 flex items-center justify-between w-full">
        <div className="flex items-center gap-2 px-3.5 py-1.5 bg-theme-surface border border-theme-border/60 rounded-full shadow-md pointer-events-auto z-20 transition-all">
          <button
            type="button" onClick={onClose}
            className="px-0.5 py-0 rounded-full text-theme-text-muted hover:bg-theme-bg/50 hover:text-theme-text transition-colors focus:outline-none flex items-center justify-center"
            title="Back to chat"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
            </svg>
          </button>
          <h1 className="text-xs font-semibold text-theme-text select-none">Settings</h1>
        </div>

        <div className="flex items-center gap-2 px-2.5 py-1 bg-theme-surface border border-theme-border/60 rounded-full shadow-md pointer-events-auto z-20 transition-all">
          <button
            type="button"
            onClick={() => onChangeTheme(isDark ? 'light' : 'dark')}
            className="p-0.5 rounded-full text-theme-text-muted hover:bg-theme-bg/50 hover:text-theme-text transition-colors focus:outline-none flex items-center justify-center"
            title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {isDark ? (
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v2.25m0 13.5V21M5.03 5.03l1.59 1.59m10.76 10.76l1.59 1.59M3 12h2.25m13.5 0H21M5.03 18.97l1.59-1.59m10.76-10.76l1.59-1.59M12 9a3 3 0 100 6 3 3 0 000-6z" />
              </svg>
            ) : (
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4">
                <path strokeLinecap="round" strokeLinejoin="round" d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z" />
              </svg>
            )}
          </button>
        </div>
      </header>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto pt-20 px-6 pb-10">
        <div className="max-w-lg mx-auto space-y-6 py-4">

          {/* ── Appearance ── */}
          <section>
            <h2 className="text-[10px] font-semibold uppercase tracking-widest text-theme-text-muted mb-3">Appearance</h2>
            <div className="bg-theme-surface border border-theme-border/50 rounded-xl divide-y divide-theme-border/30">

              {/* Theme */}
              <div className="flex items-center justify-between p-4">
                <div>
                  <p className="text-xs font-medium text-theme-text">Theme</p>
                  <p className="text-[10px] text-theme-text-muted mt-0.5">Controls the color scheme of the app</p>
                </div>
                <div className="flex items-center bg-theme-bg border border-theme-border/50 rounded-lg p-0.5 gap-0.5">
                  {themeOptions.map((opt) => (
                    <button
                      key={opt.value} type="button"
                      onClick={() => onChangeTheme(opt.value)}
                      className={`px-3 py-1 rounded-md text-[11px] font-medium transition-all ${
                        theme === opt.value
                          ? 'bg-theme-surface text-theme-text shadow-sm border border-theme-border/50'
                          : 'text-theme-text-muted hover:text-theme-text'
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Background effect toggle */}
              <div className="flex items-center justify-between p-4">
                <div>
                  <p className="text-xs font-medium text-theme-text">Background effect</p>
                  <p className="text-[10px] text-theme-text-muted mt-0.5">Interactive grid animation behind chat</p>
                </div>
                <button
                  type="button"
                  onClick={onToggleBackgroundEffect}
                  className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none ${
                    backgroundEffect ? 'bg-blue-500' : 'bg-theme-border'
                  }`}
                  role="switch"
                  aria-checked={backgroundEffect}
                >
                  <span className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow-sm transform transition-transform duration-200 ${
                    backgroundEffect ? 'translate-x-4' : 'translate-x-0'
                  }`} />
                </button>
              </div>

              {/* User bubble color */}
              <div className="flex items-center justify-between p-4">
                <div>
                  <p className="text-xs font-medium text-theme-text">User messages</p>
                  <p className="text-[10px] text-theme-text-muted mt-0.5">Background color of your messages</p>
                </div>
                <div className="flex items-center gap-1.5">
                  {BUBBLE_PRESETS.map((preset) => (
                    <button
                      key={preset.id} type="button"
                      onClick={() => onChangeUserBubble(userBubbleColor === preset.id ? '' : preset.id)}
                      title={preset.label}
                      className={`w-5 h-5 rounded-full border-2 transition-all shrink-0 ${
                        userBubbleColor === preset.id ? 'border-blue-500 scale-110 shadow-sm' : 'border-theme-border hover:border-theme-text-muted'
                      }`}
                      style={{ backgroundColor: preset.bg }}
                    />
                  ))}
                </div>
              </div>

              {/* AI bubble color */}
              <div className="flex items-center justify-between p-4">
                <div>
                  <p className="text-xs font-medium text-theme-text">AI messages</p>
                  <p className="text-[10px] text-theme-text-muted mt-0.5">Background color of assistant messages</p>
                </div>
                <div className="flex items-center gap-1.5">
                  {BUBBLE_PRESETS.map((preset) => (
                    <button
                      key={preset.id} type="button"
                      onClick={() => onChangeAiBubble(aiBubbleColor === preset.id ? '' : preset.id)}
                      title={preset.label}
                      className={`w-5 h-5 rounded-full border-2 transition-all shrink-0 ${
                        aiBubbleColor === preset.id ? 'border-blue-500 scale-110 shadow-sm' : 'border-theme-border hover:border-theme-text-muted'
                      }`}
                      style={{ backgroundColor: preset.bg }}
                    />
                  ))}
                </div>
              </div>

            </div>
          </section>

          {/* ── Profile ── */}
          <section>
            <h2 className="text-[10px] font-semibold uppercase tracking-widest text-theme-text-muted mb-3">Profile</h2>
            <div className="bg-theme-surface border border-theme-border/50 rounded-xl p-4 space-y-4">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-full bg-theme-brand text-theme-brand-text flex items-center justify-center font-bold text-sm shrink-0 select-none">
                  {avatarLetter}
                </div>
                <div className="flex-1 min-w-0">
                  <label className="text-[10px] font-medium text-theme-text-muted block mb-1">Display name</label>
                  <div className="flex items-center gap-2">
                    <input
                      type="text" value={nameInput}
                      onChange={(e) => { setNameInput(e.target.value); setNameSaved(false) }}
                      onKeyDown={(e) => e.key === 'Enter' && handleSaveName()}
                      placeholder="Your name"
                      className="flex-1 bg-theme-bg border border-theme-border rounded-lg px-3 py-1.5 text-xs text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-brand/50"
                    />
                    <button
                      type="button" onClick={handleSaveName}
                      disabled={!nameInput.trim() || nameInput.trim() === displayName}
                      className="px-3 py-1.5 text-xs bg-theme-brand text-theme-brand-text rounded-lg hover:opacity-90 transition-opacity font-semibold disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
                    >
                      {nameSaved ? 'Saved' : 'Save'}
                    </button>
                  </div>
                </div>
              </div>
              <div>
                <label className="text-[10px] font-medium text-theme-text-muted block mb-1">Email</label>
                <p className="text-xs text-theme-text-muted px-3 py-1.5 bg-theme-bg border border-theme-border/50 rounded-lg opacity-60 select-none">
                  {email || 'Not signed in'}
                </p>
              </div>
              <div className="flex items-center justify-between pt-1">
                <div>
                  <p className="text-xs font-medium text-theme-text">Sign out</p>
                  <p className="text-[10px] text-theme-text-muted mt-0.5">End your session on this device</p>
                </div>
                <button
                  type="button" onClick={onLogout}
                  className="text-xs px-3 py-1.5 bg-theme-bg border border-red-500/40 rounded-lg text-red-500 hover:bg-red-500/10 transition-colors font-semibold shrink-0"
                >
                  Sign out
                </button>
              </div>
            </div>
          </section>

          {/* ── API Keys (BYOK) ── */}
          <ApiKeysSection />

          {/* ── Chat Defaults ── */}
          <section>
            <h2 className="text-[10px] font-semibold uppercase tracking-widest text-theme-text-muted mb-3">Chat Defaults</h2>
            <div className="bg-theme-surface border border-theme-border/50 rounded-xl p-4">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-xs font-medium text-theme-text">Default model</p>
                  <p className="text-[10px] text-theme-text-muted mt-0.5">Used when starting a new conversation</p>
                </div>
                <select
                  value={defaultModel}
                  onChange={(e) => onSaveDefaultModel(e.target.value)}
                  className="text-xs bg-theme-bg border border-theme-border rounded-lg px-2.5 py-1.5 text-theme-text focus:outline-none focus:ring-1 focus:ring-theme-brand/50 cursor-pointer shrink-0"
                >
                  {models.map((m) => (
                    <option key={m.model_id} value={m.model_id}>{m.display_name}</option>
                  ))}
                  {models.length === 0 && <option value={defaultModel}>{defaultModel}</option>}
                </select>
              </div>
            </div>
          </section>

          {/* ── Keyboard Shortcuts ── */}
          <section>
            <h2 className="text-[10px] font-semibold uppercase tracking-widest text-theme-text-muted mb-3">Keyboard Shortcuts</h2>
            <div className="bg-theme-surface border border-theme-border/50 rounded-xl divide-y divide-theme-border/30">
              {SHORTCUTS.map(({ key, action }) => (
                <div key={key} className="flex items-center justify-between px-4 py-2.5">
                  <span className="text-xs text-theme-text-muted">{action}</span>
                  <kbd className="text-[10px] font-mono bg-theme-bg border border-theme-border/60 text-theme-text px-2 py-0.5 rounded-md select-none">
                    {key}
                  </kbd>
                </div>
              ))}
            </div>
          </section>

          {/* ── Data & Storage ── */}
          <section>
            <h2 className="text-[10px] font-semibold uppercase tracking-widest text-theme-text-muted mb-3">Data & Storage</h2>
            <div className="bg-theme-surface border border-theme-border/50 rounded-xl divide-y divide-theme-border/30">
              <div className="flex items-center justify-between px-4 py-3">
                <div>
                  <p className="text-xs font-medium text-theme-text">Conversations</p>
                  <p className="text-[10px] text-theme-text-muted mt-0.5">{conversations.length} saved</p>
                </div>
                <button
                  type="button" onClick={handleExport}
                  disabled={conversations.length === 0}
                  className="text-xs px-3 py-1.5 bg-theme-bg border border-theme-border rounded-lg text-theme-text hover:bg-theme-surface-hover transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Export JSON
                </button>
              </div>
              <div className="flex items-center justify-between px-4 py-3">
                <div>
                  <p className="text-xs font-medium text-theme-text">Clear all data</p>
                  <p className="text-[10px] text-theme-text-muted mt-0.5">Permanently delete all conversations</p>
                </div>
                {clearConfirm ? (
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] text-theme-text-muted select-none">Sure?</span>
                    <button
                      type="button" onClick={() => setClearConfirm(false)}
                      className="text-[10px] px-2 py-1 border border-theme-border rounded-md text-theme-text-muted hover:bg-theme-surface-hover transition-colors"
                    >No</button>
                    <button
                      type="button"
                      onClick={() => {
                        setClearConfirm(false)
                        alert('Clear all — wire to bulk delete handler from App')
                      }}
                      className="text-[10px] px-2 py-1 bg-red-600 text-white rounded-md hover:bg-red-700 transition-colors font-semibold"
                    >Yes, delete</button>
                  </div>
                ) : (
                  <button
                    type="button" onClick={() => setClearConfirm(true)}
                    disabled={conversations.length === 0}
                    className="text-xs px-3 py-1.5 bg-theme-bg border border-red-500/40 rounded-lg text-red-500 hover:bg-red-500/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    Clear all
                  </button>
                )}
              </div>
            </div>
          </section>

          {/* ── Future ── */}
          <section>
            <h2 className="text-[10px] font-semibold uppercase tracking-widest text-theme-text-muted mb-3">Future</h2>
            <div className="bg-theme-surface border border-theme-border/50 rounded-xl divide-y divide-theme-border/30">
              {FUTURE_ITEMS.map(({ label, desc }) => (
                <div key={label} className="px-4 py-3 opacity-50 select-none pointer-events-none">
                  <p className="text-xs font-medium text-theme-text">{label}</p>
                  <p className="text-[10px] text-theme-text-muted mt-0.5">{desc}</p>
                </div>
              ))}
            </div>
          </section>

          {/* ── Extras ── */}
          <section>
            <h2 className="text-[10px] font-semibold uppercase tracking-widest text-theme-text-muted mb-3">Extras</h2>
            <div className="bg-theme-surface border border-theme-border/50 rounded-xl divide-y divide-theme-border/30">
              {EXTRAS_ITEMS.map(({ label, desc }) => (
                <div key={label} className="px-4 py-3 opacity-40 select-none pointer-events-none">
                  <p className="text-xs font-medium text-theme-text">{label}</p>
                  <p className="text-[10px] text-theme-text-muted mt-0.5">{desc}</p>
                </div>
              ))}
            </div>
          </section>

        </div>
      </div>
    </div>
  )
}
