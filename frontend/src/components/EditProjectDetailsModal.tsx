import { useEffect, useState } from 'react'

interface Props {
  open: boolean
  initialName: string
  initialDescription: string
  onSave: (name: string, description: string) => void
  onCancel: () => void
}

/** F-10 — "Edit details" modal for a project (name + description), matching
 *  the reference UI: a centered dialog with a Name input and a Description
 *  textarea, Save/Cancel. Deliberately does NOT include an Archive action
 *  (skipped per the user's explicit request) -- this modal only ever edits
 *  the two text fields. */
export default function EditProjectDetailsModal({
  open,
  initialName,
  initialDescription,
  onSave,
  onCancel,
}: Props) {
  const [name, setName] = useState(initialName)
  const [description, setDescription] = useState(initialDescription)

  useEffect(() => {
    if (open) {
      setName(initialName)
      setDescription(initialDescription)
    }
  }, [open, initialName, initialDescription])

  if (!open) return null

  function handleSave() {
    onSave(name.trim(), description.trim())
  }

  return (
    // absolute (not fixed) so this centers within the page's own content area
    // (excludes the sidebar) rather than the whole viewport -- its containing
    // block is ProjectPage's `relative` root wrapper, which is exactly the
    // visible content region's own height (not affected by that div's inner
    // overflow-y-auto scroll).
    <div
      className="absolute inset-0 z-[100] flex items-center justify-center bg-black/60 animate-in fade-in duration-150"
      onClick={onCancel}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md mx-4 bg-theme-surface border border-theme-border rounded-2xl shadow-2xl p-5 animate-in zoom-in-95 duration-150"
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold text-theme-text">Edit details</h2>
          <button
            type="button"
            onClick={onCancel}
            className="text-theme-text-muted hover:text-theme-text p-1 rounded-lg hover:bg-theme-bg/50 transition-colors cursor-pointer"
            title="Close"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <label className="block text-xs font-semibold text-theme-text-muted mb-1.5">Name</label>
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') onCancel()
          }}
          className="w-full mb-4 px-3 py-2 rounded-lg bg-theme-bg border border-theme-border text-sm text-theme-text focus:outline-none focus:ring-1 focus:ring-theme-brand"
        />

        <label className="block text-xs font-semibold text-theme-text-muted mb-1.5">Description</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') onCancel()
          }}
          rows={5}
          placeholder="What's this project about?"
          className="w-full mb-5 px-3 py-2 rounded-lg bg-theme-bg border border-theme-border text-sm text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-brand resize-none"
        />

        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-3 h-8 rounded-lg border border-theme-border hover:bg-theme-surface-hover text-theme-text text-xs font-semibold transition-colors active:scale-95 cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={!name.trim()}
            className="px-3 h-8 rounded-lg bg-theme-brand hover:opacity-90 text-theme-brand-text text-xs font-semibold transition-colors active:scale-95 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  )
}
