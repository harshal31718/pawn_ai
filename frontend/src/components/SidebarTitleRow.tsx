import type { ComponentType } from 'react'
import { ChevronRightIcon } from './icons'

interface IconProps { className?: string }

interface Props {
  icon: ComponentType<IconProps>
  label: string
  onClick?: () => void
  toggle?: { collapsed: boolean; onToggle: () => void }
  /** false = sidebar is the collapsed mini rail. The icon stays pinned at
   *  the same px-3 inset either way -- only the label (and toggle chevron)
   *  animate their width/opacity to 0, so collapsing/expanding the sidebar
   *  reads as one row shrinking/growing in place rather than two unrelated
   *  layouts swapping. Defaults to true (full sidebar). */
  expanded?: boolean
  /** true = this icon is the active/selected navigation target. Shows a
   *  black-shady background in the same region as the hover effect. */
  isActive?: boolean
}

/** Shared row for the sidebar's title-level entries -- New chat, Image Lab,
 *  Projects, Chats -- so they all render as icon + label (+ optional
 *  collapse toggle, Chats only) with one consistent flat style, in both the
 *  full sidebar and the collapsed mini rail. */
export default function SidebarTitleRow({ icon: Icon, label, onClick, toggle, expanded = true, isActive = false }: Props) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={!expanded ? label : undefined}
      className={`
        group relative z-0 w-full h-7 flex items-center px-2 rounded-xl text-xs font-semibold
        overflow-hidden
        transition-all duration-300 ease-in-out active:scale-98 cursor-pointer select-none
        ${expanded ? 'gap-1' : 'gap-0'}
      `}
    >
      {/* Hover background -- always boxed to just the icon slot (matching
          the toggle button's tight w-7 hover box), in both expanded and
          collapsed states. Separate from the button's own hit area so the
          click target stays the full row either way. */}
      <span className={`absolute -z-10 inset-y-0 left-2 w-7 rounded-xl ${isActive ? 'bg-black/25 dark:bg-black/40' : 'group-hover:bg-theme-surface-hover'}`} />
      <span className="w-7 h-7 shrink-0 flex items-center justify-center">
        <Icon className={`w-4 h-4 transition-colors ${isActive ? 'text-theme-text' : 'text-theme-text-muted group-hover:text-theme-text'}`} />
      </span>
      <span
        className={`
          text-theme-text text-left truncate transition-all duration-300 ease-in-out
          ${expanded ? `opacity-100 max-w-[10rem] ${toggle ? 'flex-none' : 'flex-1'}` : 'opacity-0 max-w-0 flex-none'}
        `}
      >
        {label}
      </span>
      {toggle && (
        <span
          role="button"
          tabIndex={expanded ? 0 : -1}
          onClick={(e) => {
            if (!expanded) return
            e.stopPropagation()
            toggle.onToggle()
          }}
          onKeyDown={(e) => {
            if (!expanded) return
            if (e.key === 'Enter' || e.key === ' ') {
              e.stopPropagation()
              e.preventDefault()
              toggle.onToggle()
            }
          }}
          className={`
            p-0.5 rounded hover:bg-theme-surface text-theme-text-muted shrink-0
            transition-all duration-300 ease-in-out
            ${expanded && !toggle.collapsed ? 'opacity-0 group-hover:opacity-100 max-w-[1.5rem] pointer-events-none group-hover:pointer-events-auto' : expanded && toggle.collapsed ? 'opacity-100 max-w-[1.5rem]' : 'opacity-0 max-w-0 pointer-events-none'}
          `}
          title={toggle.collapsed ? 'Expand' : 'Collapse'}
        >
          <ChevronRightIcon className={`w-3 h-3 transition-transform ${toggle.collapsed ? '' : 'rotate-90'}`} />
        </span>
      )}
    </button>
  )
}
