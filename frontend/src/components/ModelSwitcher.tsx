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

export default function ModelSwitcher({ selected, onChange, disabled, models }: Props) {
  // Group models by level for the optgroup display
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

  return (
    <div className="flex items-center gap-1.5 px-1">
      <span className="text-xs text-zinc-400 shrink-0">Model</span>
      <select
        id="model-switcher"
        value={selected}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled || models.length === 0}
        className="
          text-xs bg-zinc-100 border border-zinc-200 rounded-md
          px-2 py-1 text-zinc-700 cursor-pointer
          hover:bg-zinc-200 focus:outline-none focus:ring-1 focus:ring-zinc-400
          disabled:opacity-50 disabled:cursor-not-allowed
          transition-colors
        "
      >
        {models.length === 0 && (
          <option value={selected}>Loading models...</option>
        )}
        {groups.map(({ level, label, models: groupModels }) =>
          groupModels.length > 0 ? (
            <optgroup key={level} label={label}>
              {groupModels.map((m) => (
                <option key={m.model_id} value={m.model_id}>
                  {m.display_name} {m.endpoint_count > 0 ? `(${m.endpoint_count})` : '(no endpoints)'}
                </option>
              ))}
            </optgroup>
          ) : null,
        )}
      </select>
    </div>
  )
}

