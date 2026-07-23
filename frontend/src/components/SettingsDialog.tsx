import type { ReactNode } from 'react'

/** Generic centered dialog for Settings sub-forms (Edit Details, Change
 *  Password) -- `absolute` (not `fixed`) and offset by `pt-14` so it centers
 *  within the settings content area only, excluding the floating navbar
 *  strip, per the user's explicit call. Click-outside (the overlay) or the
 *  X button both close it. */
export default function SettingsDialog({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: ReactNode
}) {
  return (
    <div
      className="absolute inset-0 pt-14 z-40 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm bg-theme-surface border border-theme-border rounded-xl p-5 space-y-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-theme-text">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-theme-text-muted hover:text-theme-text transition-colors cursor-pointer"
            title="Close"
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}
