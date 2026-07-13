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

/** Small "..." dropdown menu with one level of submenu (▸), used for both chat
 *  and project rows (Add to project ▸, Memory ▸, Rename, Delete). Closes on
 *  outside click; stops row-click propagation so opening it never selects the
 *  row underneath. */
export default function KebabMenu({ items, className, title = 'More options' }: Props) {
  const [open, setOpen] = useState(false)
  const [submenuIdx, setSubmenuIdx] = useState<number | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
        setSubmenuIdx(null)
      }
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [open])

  return (
    <div ref={ref} className={`relative ${className ?? ''}`} onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="p-1 rounded hover:bg-theme-surface text-theme-text-muted hover:text-theme-text transition-all active:scale-95"
        title={title}
      >
        <KebabIcon className="w-3.5 h-3.5" />
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 w-48 bg-theme-bg border border-theme-border rounded-lg shadow-lg py-1 animate-in fade-in zoom-in-95 duration-100">
          {items.map((item, i) => (
            <div
              key={item.label}
              className="relative"
              onMouseEnter={() => item.submenu && setSubmenuIdx(i)}
              onMouseLeave={() => item.submenu && setSubmenuIdx(null)}
            >
              <button
                type="button"
                onClick={() => {
                  if (item.onClick) {
                    item.onClick()
                    setOpen(false)
                  }
                }}
                className={`w-full flex items-center justify-between gap-2 px-3 py-1.5 text-xs text-left hover:bg-theme-surface-hover transition-colors cursor-pointer ${
                  item.danger ? 'text-red-500' : 'text-theme-text'
                }`}
              >
                <span className="truncate">{item.label}</span>
                {item.submenu && <ChevronRightIcon className="w-3 h-3 opacity-60 shrink-0" />}
              </button>
              {item.submenu && submenuIdx === i && (
                <div className="absolute right-full top-0 mr-1 w-48 max-h-64 overflow-y-auto bg-theme-bg border border-theme-border rounded-lg shadow-lg py-1">
                  {item.submenu.length === 0 ? (
                    <div className="px-3 py-1.5 text-xs text-theme-text-muted select-none">Nothing here</div>
                  ) : (
                    item.submenu.map((sub) => (
                      <button
                        key={sub.label}
                        type="button"
                        onClick={() => {
                          sub.onClick?.()
                          setOpen(false)
                          setSubmenuIdx(null)
                        }}
                        className={`w-full truncate px-3 py-1.5 text-xs text-left hover:bg-theme-surface-hover transition-colors cursor-pointer ${
                          sub.danger ? 'text-red-500' : 'text-theme-text'
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
