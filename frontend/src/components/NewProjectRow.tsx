import { useEffect, useRef, useState } from 'react'
import { FolderPlusIcon } from './icons'

interface Props {
  isCreating: boolean
  onCreate: (name: string) => void
  onCancel: () => void
}

/** Inline "new project" name input, shown only while actively creating one --
 *  triggered solely by the section header's "+" icon (ProjectSection.tsx's
 *  FolderPlusIcon button). Previously also rendered a standing "New project"
 *  row at the end of the list as a second trigger; removed per user
 *  feedback (visible by default, cluttering the list even when nobody was
 *  creating anything) -- the header icon is the one way in now. Split out
 *  of ProjectSection.tsx per .claude/rules/frontend.md. */
export default function NewProjectRow({ isCreating, onCreate, onCancel }: Props) {
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

  return null
}
