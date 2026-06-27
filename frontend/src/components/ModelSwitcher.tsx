import { useState } from 'react'
import type { RegistryModel } from '../api/client'

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

export default function ModelSwitcher({ selected, onChange, disabled, models }: Props) {
  const [isOpen, setIsOpen] = useState(false)
  const [expandedModels, setExpandedModels] = useState<Record<string, boolean>>({})

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

  const selectedModel = models.find((m) => m.model_id === selected)
  const buttonLabel = selectedModel 
    ? selectedModel.display_name 
    : (models.length === 0 ? 'Loading models...' : selected)

  const handleSelect = (modelId: string) => {
    onChange(modelId)
    setIsOpen(false)
    setExpandedModels({})
  }

  return (
    <div className="relative flex items-center gap-1.5 px-1">
      <span className="text-xs text-theme-text-muted shrink-0 select-none">Model</span>
      
      {/* Trigger Button */}
      <button
        id="model-switcher-button"
        type="button"
        disabled={disabled || models.length === 0}
        onClick={() => {
          if (isOpen) {
            setExpandedModels({})
          }
          setIsOpen(!isOpen)
        }}
        className="
          text-xs bg-theme-surface border border-theme-border rounded-md
          px-2.5 py-0.5 text-theme-text cursor-pointer
          hover:bg-theme-surface-hover focus:outline-none focus:ring-1 focus:ring-theme-border
          disabled:opacity-50 disabled:cursor-not-allowed
          transition-all flex items-center gap-1.5 active:scale-95 font-medium
        "
      >
        <span>{buttonLabel}</span>
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

      {/* Custom Dropdown list overlay */}
      {isOpen && (
        <div className="
          absolute right-0 top-full mt-1.5 w-80 bg-theme-bg border border-theme-border rounded-lg shadow-lg z-50 overflow-hidden text-xs py-1
          animate-in fade-in slide-in-from-top-1 duration-150
        ">
          <div className="max-h-80 overflow-y-auto">
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
                          <span className="truncate font-medium flex-1 min-w-0">{m.display_name}</span>
                          
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

