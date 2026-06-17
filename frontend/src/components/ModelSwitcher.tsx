interface Model {
  id: string
  label: string
  level: 'fast' | 'balanced' | 'research'
  sublabel?: string
}

// Hardcoded for Steps 9–10. Replaced by GET /registry/models in Step R4.
const MODELS: Model[] = [
  { id: 'groq',        label: 'Llama 3.3 70B',  sublabel: 'Groq — fastest',    level: 'fast' },
  { id: 'cerebras',   label: 'Llama 3.3 70B',  sublabel: 'Cerebras — fast',    level: 'fast' },
  { id: 'gemini',     label: 'Gemini 2.5 Flash', sublabel: 'Google',            level: 'balanced' },
  { id: 'huggingface',label: 'Llama 3.3 70B',  sublabel: 'HuggingFace',        level: 'balanced' },
  { id: 'github',     label: 'Llama 3.3 70B',  sublabel: 'GitHub Models',      level: 'balanced' },
  { id: 'openrouter', label: 'Llama 3.3 70B',  sublabel: 'OpenRouter (free)',   level: 'research' },
]

const LEVEL_LABELS: Record<Model['level'], string> = {
  fast:     '⚡ Fast',
  balanced: '⚖️ Balanced',
  research: '🔬 Research',
}

interface Props {
  selected: string
  onChange: (id: string) => void
  disabled?: boolean
}

export default function ModelSwitcher({ selected, onChange, disabled }: Props) {
  // Group models by level for the optgroup display
  const groups = (['fast', 'balanced', 'research'] as const).map((level) => ({
    level,
    label: LEVEL_LABELS[level],
    models: MODELS.filter((m) => m.level === level),
  }))

  return (
    <div className="flex items-center gap-1.5 px-1">
      <span className="text-xs text-zinc-400 shrink-0">Model</span>
      <select
        id="model-switcher"
        value={selected}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="
          text-xs bg-zinc-100 border border-zinc-200 rounded-md
          px-2 py-1 text-zinc-700 cursor-pointer
          hover:bg-zinc-200 focus:outline-none focus:ring-1 focus:ring-zinc-400
          disabled:opacity-50 disabled:cursor-not-allowed
          transition-colors
        "
      >
        {groups.map(({ level, label, models }) =>
          models.length > 0 ? (
            <optgroup key={level} label={label}>
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.sublabel ? `${m.label} — ${m.sublabel}` : m.label}
                </option>
              ))}
            </optgroup>
          ) : null,
        )}
      </select>
    </div>
  )
}
