import { useRef, useState } from 'react'
import { AUTO_MODEL_ID, type RegistryModel } from '../api/client'

const DROPDOWN_MAX_HEIGHT = 320 // px, matches the old fixed max-h-80
const VIEWPORT_MARGIN = 8 // px breathing room from the viewport edge

const LEVEL_LABELS: Record<string, string> = {
  fast:     '⚡ Fast',
  balanced: '⚖️ Balanced',
  research: '🔬 Research',
}

interface Props {
  selected: string
  onChange: (id: string) => void
  disabled?: boolean
  models: RegistryModel[]
  // ProvidersPage's "Default Model" trigger: shows this literal, static
  // label instead of the selected model's name (and hides the provider
  // suffix span) -- same dropdown, different trigger text/style, so tab
  // trays that want a fixed label don't have to duplicate the whole
  // dropdown implementation.
  triggerLabel?: string
}

const formatProviderName = (p: string) => {
  if (!p) return ''
  if (p === 'huggingface') return 'HuggingFace'
  if (p === 'openrouter') return 'OpenRouter'
  if (p === 'github') return 'GitHub'
  return p.charAt(0).toUpperCase() + p.slice(1)
}

const formatProviderList = (providers?: string[]) => {
  if (!providers || providers.length === 0) return 'No Endpoints'
  if (providers.length <= 2) {
    return providers.map(formatProviderName).join(', ')
  }
  const firstTwo = providers.slice(0, 2).map(formatProviderName).join(', ')
  return `${firstTwo} +${providers.length - 2} more`
}

export default function ModelSwitcher({ selected, onChange, disabled, models, triggerLabel }: Props) {
  const [isOpen, setIsOpen] = useState(false)
  const [expandedModels, setExpandedModels] = useState<Record<string, boolean>>({})
  const triggerRef = useRef<HTMLButtonElement>(null)
  // F-2 follow-up (user-reported live): the dropdown always opened upward,
  // assuming the trigger sits near the bottom of the viewport (true in the
  // main chat composer, not true everywhere it's used e.g. ProjectPage) --
  // overflowed off the top of the screen when there wasn't enough room
  // above. Now computed on open: flips to open downward, and caps its own
  // height to whichever space is actually available, so it's never clipped.
  const [dropdownPlacement, setDropdownPlacement] = useState<{ direction: 'up' | 'down'; maxHeight: number }>({
    direction: 'up',
    maxHeight: DROPDOWN_MAX_HEIGHT,
  })

  // Group models by level for the display list
  const levelsOrder = ['fast', 'balanced', 'research'] as const

  const groups: Array<{
    level: string
    label: string
    models: RegistryModel[]
  }> = levelsOrder.map((level) => ({
    level,
    label: LEVEL_LABELS[level] || level,
    models: models.filter((m) => m.capability_level === level),
  }))

  const otherModels = models.filter(
    (m) => !m.capability_level || !levelsOrder.includes(m.capability_level as any)
  )
  if (otherModels.length > 0) {
    groups.push({
      level: 'other',
      label: '⚙️ Other',
      models: otherModels,
    })
  }

  const isAuto = selected === AUTO_MODEL_ID
  const selectedModel = models.find((m) => m.model_id === selected)
  const buttonLabel = isAuto
    ? '✨ Auto'
    : selectedModel
      ? selectedModel.display_name
      : (models.length === 0 ? 'Loading models...' : selected)

  const handleSelect = (modelId: string) => {
    onChange(modelId)
    setIsOpen(false)
    setExpandedModels({})
  }

  return (
    <div className="relative flex items-center px-1">
      {/* Trigger Button */}
      <button
        ref={triggerRef}
        id="model-switcher-button"
        type="button"
        // C5: no longer disabled on an empty model list -- Auto is always a
        // valid choice, so the dropdown must stay reachable even before the
        // registry has loaded (or when the user holds no keys yet).
        disabled={disabled}
        onClick={() => {
          if (isOpen) {
            setExpandedModels({})
          } else if (triggerRef.current) {
            const rect = triggerRef.current.getBoundingClientRect()
            const spaceAbove = rect.top - VIEWPORT_MARGIN
            const spaceBelow = window.innerHeight - rect.bottom - VIEWPORT_MARGIN
            const direction = spaceAbove >= DROPDOWN_MAX_HEIGHT || spaceAbove >= spaceBelow ? 'up' : 'down'
            const available = direction === 'up' ? spaceAbove : spaceBelow
            setDropdownPlacement({ direction, maxHeight: Math.max(120, Math.min(DROPDOWN_MAX_HEIGHT, available)) })
          }
          setIsOpen(!isOpen)
        }}
        className={
          triggerLabel
            ? `
              text-[11px] font-semibold uppercase tracking-wide bg-theme-surface border border-theme-border/50 rounded-xl
              px-4 py-1.5 text-theme-text-muted hover:text-theme-text cursor-pointer
              focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed
              transition-all flex items-center gap-1.5 active:scale-95
            `
            : `
              text-xs bg-theme-surface border border-theme-border rounded-md
              px-2.5 py-0.5 text-theme-text cursor-pointer
              hover:bg-theme-surface-hover focus:outline-none focus:ring-1 focus:ring-theme-border
              disabled:opacity-50 disabled:cursor-not-allowed
              transition-all flex items-center gap-1.5 active:scale-95 font-medium
            `
        }
      >
        <span>{triggerLabel ?? buttonLabel}</span>
        {!triggerLabel && selectedModel?.providers?.[0] && !disabled && (
          <span className="text-theme-text-muted font-normal opacity-70">
            · {formatProviderName(selectedModel.providers[0])}
          </span>
        )}
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          className={`w-3 h-3 text-theme-text-muted transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`}
        >
          <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
        </svg>
      </button>

      {/* Backdrop for closing click-outside */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-transparent"
          onClick={() => {
            setIsOpen(false)
            setExpandedModels({})
          }}
        />
      )}

      {/* Custom Dropdown list overlay -- direction/height computed on open (see
          the trigger's onClick) so it never overflows off the viewport edge. */}
      {isOpen && (
        <div
          className={`
            absolute right-0 w-80 bg-theme-bg border border-theme-border rounded-lg shadow-lg z-50 overflow-hidden text-xs py-1
            animate-in fade-in duration-150
            ${dropdownPlacement.direction === 'up' ? 'bottom-full mb-1.5 slide-in-from-bottom-1' : 'top-full mt-1.5 slide-in-from-top-1'}
          `}
        >
          <div className="overflow-y-auto" style={{ maxHeight: dropdownPlacement.maxHeight }}>
            {/* C5: Auto -- pinned above every category. Not a registry model;
                selecting it omits model_id from the request so the backend
                routes by capability (level + task type). */}
            <button
              type="button"
              onClick={() => handleSelect(AUTO_MODEL_ID)}
              className={`w-full text-left px-3 py-2 transition-colors border-b border-theme-border/20 cursor-pointer ${
                isAuto ? 'bg-theme-brand/10' : 'hover:bg-theme-surface/60'
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className={`font-medium ${isAuto ? 'text-theme-brand' : 'text-theme-text'}`}>
                  ✨ Auto
                </span>
                {isAuto && <span className="text-theme-brand shrink-0">✓</span>}
              </div>
              <p className="text-[10px] text-theme-text-muted mt-0.5 leading-relaxed">
                Picks the best available model for each task
              </p>
            </button>

            {groups.map(({ level, label, models: groupModels }) =>
              groupModels.length > 0 ? (
                <div key={level} className="flex flex-col">
                  {/* Category Header */}
                  <div className="px-3 py-1 text-[10px] font-bold uppercase tracking-wider text-theme-text-muted bg-theme-surface/40 select-none border-b border-theme-border/20 border-t border-theme-border/10 first:border-t-0">
                    {label}
                  </div>
                  
                  {/* Models list inside category */}
                  <div className="py-0.5">
                    {groupModels.map((m) => {
                      const isOptionSelected = m.model_id === selected
                      const isExpanded = !!expandedModels[m.model_id]
                      return (
                        <button
                          key={m.model_id}
                          type="button"
                          onClick={() => handleSelect(m.model_id)}
                          className={`
                            w-full flex items-center justify-between px-3 py-2 text-left hover:bg-theme-surface-hover transition-colors gap-4
                            ${isOptionSelected ? 'bg-theme-surface font-semibold text-theme-text' : 'text-theme-text'}
                          `}
                        >
                          <div className="flex items-center gap-1.5 min-w-0 flex-1">
                            {isOptionSelected ? (
                              <svg className="w-3 h-3 shrink-0 text-theme-brand" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                              </svg>
                            ) : (
                              <span className="w-3 h-3 shrink-0" />
                            )}
                            <span className="truncate font-medium">{m.display_name}</span>
                          </div>
                          
                          {m.providers.length > 2 ? (
                            isExpanded ? (
                              <span
                                onClick={(e) => {
                                  e.stopPropagation()
                                  setExpandedModels((prev) => ({ ...prev, [m.model_id]: false }))
                                }}
                                className="text-[10px] text-theme-text-muted hover:text-theme-text font-mono tracking-wide shrink-0 cursor-pointer select-none bg-theme-surface px-1 py-0.5 rounded border border-theme-border/50 transition-colors"
                                title="Click to collapse providers"
                              >
                                {m.providers.map(formatProviderName).join(', ')}
                              </span>
                            ) : (
                              <span
                                onClick={(e) => {
                                  e.stopPropagation()
                                  setExpandedModels((prev) => ({ ...prev, [m.model_id]: true }))
                                }}
                                className="text-[10px] text-theme-text-muted hover:text-theme-text font-mono tracking-wide shrink-0 cursor-pointer select-none bg-theme-surface px-1 py-0.5 rounded border border-theme-border/50 transition-colors"
                                title="Click to show all providers"
                              >
                                {formatProviderList(m.providers)}
                              </span>
                            )
                          ) : (
                            <span className="text-[10px] text-theme-text-muted font-mono tracking-wide shrink-0 select-none">
                              {m.providers.map(formatProviderName).join(', ')}
                            </span>
                          )}
                        </button>
                      )
                    })}
                  </div>
                </div>
              ) : null
            )}
          </div>
        </div>
      )}
    </div>
  )
}

