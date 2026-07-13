import { useEffect, useRef, useState } from 'react'
import { FolderPlusIcon } from './icons'

interface Props {
  isCreating: boolean
  onStartCreate: () => void
  onCreate: (name: string) => void
  onCancel: () => void
}

/** "New project" affordance sibling to Sidebar's "New chat" button — a row at
 *  the end of the projects list that opens an inline name input. Also
 *  triggered externally (e.g. the section header's "+" icon) via isCreating.
 *  Split out of ProjectSection.tsx per .claude/rules/frontend.md. */
export default function NewProjectRow({ isCreating, onStartCreate, onCreate, onCancel }: Props) {
  const [value, setValue] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (isCreating && inputRef.current) {
      inputRef.current.focus()
    } else if (!isCreating) {
      setValue('')
    }
  }, [isCreating])

  function confirm() {
    const trimmed = value.trim()
    if (trimmed) onCreate(trimmed)
    else onCancel()
  }

  if (isCreating) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded-lg">
        <FolderPlusIcon className="w-3.5 h-3.5 shrink-0 text-theme-text-muted" />
        <input
          ref={inputRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onBlur={onCancel}
          onKeyDown={(e) => {
            if (e.key === 'Enter') confirm()
            else if (e.key === 'Escape') onCancel()
          }}
          placeholder="Project name"
          className="flex-1 bg-theme-bg border border-theme-border rounded px-1.5 py-0.5 text-xs text-theme-text focus:outline-none focus:ring-1 focus:ring-theme-border"
        />
      </div>
    )
  }

  return (
    <button
      type="button"
      onClick={onStartCreate}
      className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium text-theme-text-muted hover:bg-theme-surface-hover hover:text-theme-text transition-all cursor-pointer select-none"
    >
      <FolderPlusIcon className="w-3.5 h-3.5 shrink-0" />
      <span>New project</span>
    </button>
  )
}
