import { useState } from 'react'
import type { Citation } from '../types'

interface Props {
  citations: Citation[]
}

/** How many chips render before the rest fold behind a "Sources" dropdown
 *  (2026-07-13 UX revision: long source lists were flooding the message). */
const VISIBLE_LIMIT = 5

/** Source chips for an assistant message — stay visible regardless of the
 *  trace collapse state (Phase A / A.8: "outside the collapsible block").
 *  Beyond VISIBLE_LIMIT, chips collapse behind a "+N sources" toggle. */
export default function CitationChips({ citations }: Props) {
  const [expanded, setExpanded] = useState(false)
  const safe = citations.filter((c) => /^https?:\/\//i.test(c.url)) // reject javascript:/data: etc.
  if (safe.length === 0) return null

  const overflow = safe.length - VISIBLE_LIMIT
  const shown = expanded ? safe : safe.slice(0, VISIBLE_LIMIT)

  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5 px-2">
      {shown.map((c, idx) => (
        <a
          key={idx}
          href={c.url}
          target="_blank"
          rel="noopener noreferrer"
          title={c.url}
          className="inline-flex items-center px-2 py-0.5 rounded-full bg-theme-surface
                     border border-theme-border/40 text-[10px] text-theme-text-muted
                     font-medium leading-none hover:text-theme-text hover:border-theme-border
                     transition-colors max-w-[220px] truncate"
        >
          {c.title || c.url}
        </a>
      ))}
      {overflow > 0 && (
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-theme-surface-hover
                     border border-theme-border/60 text-[10px] text-theme-text-muted font-semibold
                     leading-none hover:text-theme-text transition-colors cursor-pointer"
        >
          {expanded ? 'Show less' : `+${overflow} sources`}
          <svg
            className={`w-2.5 h-2.5 transform transition-transform ${expanded ? 'rotate-180' : ''}`}
            fill="none" stroke="currentColor" viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M19 9l-7 7-7-7" />
          </svg>
        </button>
      )}
    </div>
  )
}
