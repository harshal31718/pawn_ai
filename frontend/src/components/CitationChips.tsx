import type { Citation } from '../types'

interface Props {
  citations: Citation[]
}

/** Source chips for an assistant message — stay visible regardless of the
 *  trace collapse state (Phase A / A.8: "outside the collapsible block"). */
export default function CitationChips({ citations }: Props) {
  const safe = citations.filter((c) => /^https?:\/\//i.test(c.url)) // reject javascript:/data: etc.
  if (safe.length === 0) return null

  return (
    <div className="mt-1.5 flex flex-wrap gap-1.5 px-2">
      {safe.map((c, idx) => (
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
    </div>
  )
}
