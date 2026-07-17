import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
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
  /** Override the trigger's icon (defaults to the "⋮" KebabIcon) -- e.g. the
   *  composer's attach menu (F-11) uses a "+" instead. */
  icon?: ReactNode
  /** Override the trigger button's own classes (defaults to the small "⋮"
   *  row-action style) -- e.g. the composer's attach menu (F-11) needs the
   *  bigger circular button size the rest of its toolbar uses. */
  buttonClassName?: string
}

/** Small "..." dropdown menu with one level of submenu, used for both chat
 *  and project rows (Add to project ▸, Memory ▸, Rename, Delete). Submenus
 *  expand INLINE below their parent item (accordion), never as a side
 *  flyout — the sidebar's overflow-hidden/overflow-y-auto ancestors clip any
 *  absolutely-positioned flyout, and a left-edge sidebar pushes a right-full
 *  flyout off-screen.
 *
 *  The open dropdown itself renders through a React portal into
 *  document.body, positioned via `position: fixed` from the trigger
 *  button's own bounding rect — NOT as a normal absolutely-positioned
 *  descendant. This sidesteps a real bug found live: the sidebar's sticky
 *  "Projects"/"Chats" section labels (F-9) are explicitly z-indexed
 *  (position: sticky + z-index), which per CSS stacking rules always paints
 *  above any *non-positioned* ancestor's subtree regardless of how high a
 *  z-index a descendant deep inside that subtree sets on itself — so the
 *  dropdown's own z-50 could never actually out-rank the sticky headers
 *  while it stayed nested inside the (non-positioned) scrollable list. A
 *  portal escapes that ancestor chain entirely instead of trying to out-z-
 *  index it locally, which only works within the same stacking context.
 *
 *  Closes on outside click (checked against BOTH the trigger and the
 *  portaled dropdown, since they're no longer in the same DOM subtree) and
 *  on scroll/resize (position is computed once on open, not tracked live —
 *  simplest robust choice given how short-lived this menu is). Stops
 *  row-click propagation so opening it never selects the row underneath.
 *
 *  Opens downward by default, but flips upward when there's more room above
 *  the trigger than below (same viewport-flip logic `ModelSwitcher.tsx`
 *  gained after an identical live bug: a trigger near the bottom of the
 *  viewport -- e.g. a composer's `+` button -- would otherwise render the
 *  menu partly/fully off-screen). Anchored via `top`/`bottom` (whichever
 *  matches the chosen direction) rather than a fixed height, so it still
 *  grows correctly from that edge if a submenu expands after opening. */
export default function KebabMenu({ items, className, title = 'More options', icon, buttonClassName }: Props) {
  const [open, setOpen] = useState(false)
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)
  const [coords, setCoords] = useState<
    { direction: 'down'; top: number; right: number } | { direction: 'up'; bottom: number; right: number } | null
  >(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return

    function onDocClick(e: MouseEvent) {
      const target = e.target as Node
      if (triggerRef.current?.contains(target)) return
      if (dropdownRef.current?.contains(target)) return
      closeAll()
    }
    function onScrollOrResize() {
      // Simplest robust choice: a stale-positioned dropdown mid-scroll looks
      // worse than one that just closes -- reopening is one click away.
      closeAll()
    }

    document.addEventListener('mousedown', onDocClick)
    window.addEventListener('scroll', onScrollOrResize, true) // capture: scrollable ancestors don't bubble
    window.addEventListener('resize', onScrollOrResize)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      window.removeEventListener('scroll', onScrollOrResize, true)
      window.removeEventListener('resize', onScrollOrResize)
    }
  }, [open])

  function closeAll() {
    setOpen(false)
    setExpandedIdx(null)
  }

  function handleTriggerClick() {
    if (!open && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect()
      const right = window.innerWidth - rect.right
      const spaceBelow = window.innerHeight - rect.bottom
      const spaceAbove = rect.top
      if (spaceBelow >= 160 || spaceBelow >= spaceAbove) {
        setCoords({ direction: 'down', top: rect.bottom + 4, right })
      } else {
        setCoords({ direction: 'up', bottom: window.innerHeight - rect.top + 4, right })
      }
    }
    setOpen((v) => !v)
    setExpandedIdx(null)
  }

  return (
    <div className={className} onClick={(e) => e.stopPropagation()}>
      <button
        ref={triggerRef}
        type="button"
        onClick={handleTriggerClick}
        className={buttonClassName ?? 'p-1 rounded hover:bg-theme-surface text-theme-text-muted hover:text-theme-text transition-all active:scale-95'}
        title={title}
      >
        {icon ?? <KebabIcon className="w-3.5 h-3.5" />}
      </button>
      {open && coords && createPortal(
        <div
          ref={dropdownRef}
          style={{
            position: 'fixed',
            right: coords.right,
            zIndex: 9999,
            ...(coords.direction === 'down' ? { top: coords.top } : { bottom: coords.bottom }),
          }}
          className="w-48 max-h-[70vh] overflow-y-auto bg-theme-bg border border-theme-border rounded-lg shadow-lg py-1 animate-in fade-in zoom-in-95 duration-100"
          onClick={(e) => e.stopPropagation()}
        >
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
        </div>,
        document.body,
      )}
    </div>
  )
}
