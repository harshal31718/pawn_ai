/** 2026-07-23: shared col1/col2 header used at the top of every tab on the
 *  Providers page (Models, Providers (BYOK), Admin) -- one definition so the
 *  layout can't drift between tabs.
 *  Col 1: row 1 description text, row 2 search bar.
 *  Col 2: a green, uppercase headline number + label, vertically centered
 *  against the whole col 1 block.
 *
 *  Rendered by ProvidersPage.tsx as part of its single sticky block (tray +
 *  this header, together) -- it does not manage its own stickiness or
 *  position, so it never needs to know the tray's height.
 */
export default function TabHeaderCard({
  message,
  search,
  onSearchChange,
  searchPlaceholder,
  value,
  label,
}: {
  message: string
  search: string
  onSearchChange: (v: string) => void
  searchPlaceholder: string
  value: string | number
  label: string
}) {
  return (
    <div className="bg-theme-surface border border-theme-border/50 rounded-xl p-3">
      <div className="flex items-stretch gap-3">
        <div className="flex-1 min-w-0 flex flex-col justify-center gap-2">
          <p className="text-[10px] text-theme-text-muted leading-relaxed">{message}</p>
          <input
            type="text"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder={searchPlaceholder}
            className="flex-1 min-w-0 bg-theme-bg border border-theme-border rounded-lg px-3 py-1.5 text-xs text-theme-text placeholder-theme-text-muted focus:outline-none focus:ring-1 focus:ring-theme-brand/50"
          />
        </div>
        <div className="flex flex-col items-center justify-center shrink-0 leading-none select-none px-2 uppercase">
          <p className="text-lg font-semibold text-emerald-600 dark:text-emerald-400">{value}</p>
          <p className="text-[9px] text-emerald-600 dark:text-emerald-400 tracking-wide mt-0.5 whitespace-nowrap">
            {label}
          </p>
        </div>
      </div>
    </div>
  )
}
