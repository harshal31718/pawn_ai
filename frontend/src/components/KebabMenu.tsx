import { useEffect, useRef, useState } from 'react'
import { ChevronRightIcon, KebabIcon } from './icons'

export interface MenuItem {
  label: string
  onClick?: () => void
  danger?: boolean
  submenu?: MenuItem[]
}

interface Props {
  items: MenuItem[]
  className?: string
  title?: string
}

/** Small "..." dropdown menu with one level of submenu, used for both chat
 *  and project rows (Add to project ▸, Memory ▸, Rename, Delete). Submenus
 *  expand INLINE below their parent item (accordion), never as a side
 *  flyout — the sidebar's overflow-hidden/overflow-y-auto ancestors clip any
 *  absolutely-positioned flyout, and a left-edge sidebar pushes a right-full
 *  flyout off-screen. Closes on outside click; stops row-click propagation so
 *  opening it never selects the row underneath. */
export default function KebabMenu({ items, className, title = 'More options' }: Props) {
  const [open, setOpen] = useState(false)
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
        setExpandedIdx(null)
      }
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [open])

  function closeAll() {
    setOpen(false)
    setExpandedIdx(null)
  }

  return (
    <div ref={ref} className={`relative ${className ?? ''}`} onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        onClick={() => {
          setOpen((v) => !v)
          setExpandedIdx(null)
        }}
        className="p-1 rounded hover:bg-theme-surface text-theme-text-muted hover:text-theme-text transition-all active:scale-95"
        title={title}
      >
        <KebabIcon className="w-3.5 h-3.5" />
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 w-48 bg-theme-bg border border-theme-border rounded-lg shadow-lg py-1 animate-in fade-in zoom-in-95 duration-100">
          {items.map((item, i) => (
            <div key={item.label}>
              <button
                type="button"
                onClick={() => {
                  if (item.submenu) {
                    setExpandedIdx((cur) => (cur === i ? null : i))
                  } else if (item.onClick) {
                    item.onClick()
                    closeAll()
                  }
                }}
                className={`w-full flex items-center justify-between gap-2 px-3 py-1.5 text-xs text-left hover:bg-theme-surface-hover transition-colors cursor-pointer ${
                  item.danger ? 'text-red-500' : 'text-theme-text'
                }`}
              >
                <span className="truncate">{item.label}</span>
                {item.submenu && (
                  <ChevronRightIcon
                    className={`w-3 h-3 opacity-60 shrink-0 transition-transform ${
                      expandedIdx === i ? 'rotate-90' : ''
                    }`}
                  />
                )}
              </button>
              {item.submenu && expandedIdx === i && (
                <div className="border-l border-theme-border/50 ml-3 max-h-48 overflow-y-auto">
                  {item.submenu.length === 0 ? (
                    <div className="px-3 py-1.5 text-xs text-theme-text-muted select-none">Nothing here</div>
                  ) : (
                    item.submenu.map((sub) => (
                      <button
                        key={sub.label}
                        type="button"
                        onClick={() => {
                          sub.onClick?.()
                          closeAll()
                        }}
                        className={`w-full truncate px-3 py-1.5 text-xs text-left hover:bg-theme-surface-hover transition-colors cursor-pointer ${
                          sub.danger ? 'text-red-500' : 'text-theme-text-muted hover:text-theme-text'
                        }`}
                      >
                        {sub.label}
                      </button>
                    ))
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
