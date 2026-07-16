import { useEffect, useState } from 'react'

interface Props {
  open: boolean
  onCreate: (name: string, description: string) => void
  onCancel: () => void
}

/** Blocking name (required) + description (optional) dialog shown on "New
 *  project" — replaces the old flow where clicking "New project" silently
 *  created an unnamed draft that only got a real, synced project id (still
 *  carrying the placeholder name "New Project" if the user never renamed it)
 *  once you started a chat inside it. Requiring the name upfront means a
 *  project is never created without one. */
export default function NewProjectDialog({ open, onCreate, onCancel }: Props) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  useEffect(() => {
    if (open) {
      setName('')
      setDescription('')
    }
  }, [open])

  if (!open) return null

  function handleCreate() {
    const trimmed = name.trim()
    if (!trimmed) return
    onCreate(trimmed, description.trim())
  }

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 animate-in fade-in duration-150"
      onClick={onCancel}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md mx-4 bg-theme-surface border border-theme-border rounded-2xl shadow-2xl p-5 animate-in zoom-in-95 duration-150"
      >
        <h2 className="text-base font-semibold text-theme-text mb-4">New project</h2>

        <label className="block text-xs font-semibold text-theme-text-muted mb-1.5">Name</label>
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleCreate()
            else if (e.key === 'Escape') onCancel()
          }}
          placeholder="Project name"
          className="w-full mb-4 px-3 py-2 rounded-lg bg-theme-bg border border-theme-border text-sm text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-brand"
        />

        <label className="block text-xs font-semibold text-theme-text-muted mb-1.5">
          Description <span className="font-normal opacity-60">(optional)</span>
        </label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') onCancel()
          }}
          rows={4}
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
            onClick={handleCreate}
            disabled={!name.trim()}
            className="px-3 h-8 rounded-lg bg-theme-brand hover:opacity-90 text-theme-brand-text text-xs font-semibold transition-colors active:scale-95 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Create
          </button>
        </div>
      </div>
    </div>
  )
}
