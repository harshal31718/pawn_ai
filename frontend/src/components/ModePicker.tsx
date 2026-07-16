import { useState } from 'react'

export type Mode = 'fast' | 'pro' | 'image'

const OPTIONS: Array<{ id: Mode; label: string }> = [
  { id: 'fast', label: 'Fast' },
  { id: 'pro', label: 'Pro' },
  { id: 'image', label: 'Create Image' },
]

interface Props {
  value: Mode
  onChange: (mode: Mode) => void
}

/** Composer's mode picker -- sits in the old model-switcher slot. A hard
 *  hint sent to the backend router (graph.py classify_node): fast -> direct
 *  answer, pro -> full agent planning, image -> agent loop tuned for a
 *  single generate_image tool call. */
export default function ModePicker({ value, onChange }: Props) {
  const [isOpen, setIsOpen] = useState(false)
  const selected = OPTIONS.find((o) => o.id === value) ?? OPTIONS[0]

  return (
    <div className="relative flex items-center px-1">
      <button
        type="button"
        onClick={() => setIsOpen((v) => !v)}
        className="
          text-xs bg-theme-surface border border-theme-border rounded-md
          px-2.5 py-0.5 text-theme-text cursor-pointer
          hover:bg-theme-surface-hover focus:outline-none focus:ring-1 focus:ring-theme-border
          transition-all flex items-center gap-1.5 active:scale-95 font-medium
        "
      >
        <span>{selected.label}</span>
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          className={`w-3 h-3 text-theme-text-muted transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`}
        >
          <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
        </svg>
      </button>

      {isOpen && (
        <div className="fixed inset-0 z-40 bg-transparent" onClick={() => setIsOpen(false)} />
      )}

      {isOpen && (
        <div
          className="
            absolute right-0 bottom-full mb-1.5 w-40 bg-theme-bg border border-theme-border
            rounded-lg shadow-lg z-50 overflow-hidden text-xs py-1
            animate-in fade-in slide-in-from-bottom-1 duration-150
          "
        >
          {OPTIONS.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => {
                onChange(option.id)
                setIsOpen(false)
              }}
              className={`
                w-full flex items-center gap-1.5 px-3 py-2 text-left hover:bg-theme-surface-hover transition-colors
                ${option.id === value ? 'bg-theme-surface font-semibold text-theme-text' : 'text-theme-text'}
              `}
            >
              {option.id === value ? (
                <svg className="w-3 h-3 shrink-0 text-theme-brand" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                </svg>
              ) : (
                <span className="w-3 h-3 shrink-0" />
              )}
              <span className="truncate">{option.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
