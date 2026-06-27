import { useState } from 'react'

interface Props {
  isOpen: boolean
  onClose: () => void
  darkMode: boolean
  onToggleDarkMode: () => void
  displayName: string
  onSaveDisplayName: (name: string) => void
}

export default function SettingsModal({
  isOpen,
  onClose,
  darkMode,
  onToggleDarkMode,
  displayName,
  onSaveDisplayName,
}: Props) {
  const [nameInput, setNameInput] = useState(displayName)

  if (!isOpen) return null

  function handleSave() {
    const trimmed = nameInput.trim()
    if (trimmed) onSaveDisplayName(trimmed)
    onClose()
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter') handleSave()
    else if (e.key === 'Escape') onClose()
  }

  const avatarLetter = nameInput.trim()[0]?.toUpperCase() || 'U'

  return (
    <>
      <div
        className="fixed inset-0 bg-black/50 z-50 animate-in fade-in duration-150"
        onClick={onClose}
      />
      <div className="fixed inset-0 flex items-center justify-center z-50 pointer-events-none p-4">
        <div className="bg-theme-surface border border-theme-border rounded-2xl shadow-2xl w-full max-w-sm pointer-events-auto animate-in zoom-in-95 fade-in duration-150">

          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-theme-border/50">
            <div className="flex items-center gap-2.5">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4 text-theme-text-muted">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.43l-1.003.828c-.293.241-.438.613-.43.992a7.723 7.723 0 010 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.43l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 010-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.645-.869L9.594 3.94z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
              <h2 className="text-sm font-semibold text-theme-text">Settings</h2>
            </div>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-theme-text-muted hover:text-theme-text hover:bg-theme-bg/50 transition-colors"
            >
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <div className="p-5 space-y-6">
            {/* Appearance */}
            <section className="space-y-3">
              <h3 className="text-[10px] font-semibold text-theme-text-muted uppercase tracking-widest">Appearance</h3>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-medium text-theme-text">Dark mode</p>
                  <p className="text-[10px] text-theme-text-muted mt-0.5">Switch between light and dark theme</p>
                </div>
                <button
                  type="button"
                  onClick={onToggleDarkMode}
                  role="switch"
                  aria-checked={darkMode}
                  className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors duration-200 focus:outline-none ${darkMode ? 'bg-theme-brand' : 'bg-theme-border'}`}
                >
                  <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform duration-200 ${darkMode ? 'translate-x-[18px]' : 'translate-x-[3px]'}`} />
                </button>
              </div>
            </section>

            {/* Profile */}
            <section className="space-y-3">
              <h3 className="text-[10px] font-semibold text-theme-text-muted uppercase tracking-widest">Profile</h3>
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-full bg-theme-brand text-theme-brand-text flex items-center justify-center font-bold text-sm shadow-sm shrink-0 select-none">
                  {avatarLetter}
                </div>
                <input
                  type="text"
                  value={nameInput}
                  onChange={(e) => setNameInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Display name"
                  className="flex-1 bg-theme-bg border border-theme-border rounded-lg px-3 py-1.5 text-xs text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-brand/50"
                />
              </div>
            </section>
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-2 px-5 py-3.5 border-t border-theme-border/50">
            <button
              type="button"
              onClick={onClose}
              className="px-3.5 py-1.5 text-xs text-theme-text-muted hover:text-theme-text rounded-lg hover:bg-theme-bg/50 transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              className="px-3.5 py-1.5 text-xs bg-theme-brand text-theme-brand-text rounded-lg hover:opacity-90 transition-opacity font-semibold"
            >
              Save
            </button>
          </div>

        </div>
      </div>
    </>
  )
}
