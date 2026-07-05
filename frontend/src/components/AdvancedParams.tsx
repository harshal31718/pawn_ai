import { useState, useEffect } from 'react'
import type { ImageParams } from '../api/client'
import { STYLE_PRESET_KEY_MAP } from '../types'

const RATIO_TO_SIZE: Record<string, { width: number; height: number }> = {
  '1:1': { width: 512, height: 512 },
  '16:9': { width: 1024, height: 576 },
  '9:16': { width: 576, height: 1024 },
  '4:3': { width: 768, height: 576 },
}

interface ParamState<T> {
  enabled: boolean
  value: T
}

export interface AdvancedState {
  aspectRatio: ParamState<string>
  steps: ParamState<number>
  guidanceScale: ParamState<number>
  negativePrompt: ParamState<string>
  stylePreset: ParamState<string>
  strength: ParamState<number>
}

// Per-model floor: SDXL wants ~30 steps for good quality (its notebook default);
// FLUX.1-schnell is distilled for ~4 steps and gains nothing from more. Used so a
// user who enables the slider without touching it gets a sane value either way,
// instead of one flat default that undercuts SDXL or overshoots FLUX.
export const DEFAULT_STEPS: Record<string, number> = { sdxl: 30, flux: 4 }

export function initialAdvanced(modelId: string): AdvancedState {
  return {
    aspectRatio: { enabled: false, value: '1:1' },
    steps: { enabled: false, value: DEFAULT_STEPS[modelId] ?? 20 },
    guidanceScale: { enabled: false, value: 7.5 },
    negativePrompt: { enabled: false, value: '' },
    stylePreset: { enabled: false, value: '' },
    strength: { enabled: false, value: 0.6 },
  }
}

export const INITIAL_ADVANCED: AdvancedState = initialAdvanced('sdxl')

export function deriveParams(s: AdvancedState): ImageParams {
  const p: ImageParams = {}
  if (s.aspectRatio.enabled && RATIO_TO_SIZE[s.aspectRatio.value]) {
    const sz = RATIO_TO_SIZE[s.aspectRatio.value]
    p.width = sz.width
    p.height = sz.height
  }
  if (s.steps.enabled) p.num_inference_steps = s.steps.value
  if (s.guidanceScale.enabled) p.guidance_scale = s.guidanceScale.value
  if (s.negativePrompt.enabled && s.negativePrompt.value.trim())
    p.negative_prompt = s.negativePrompt.value.trim()
  if (s.stylePreset.enabled && s.stylePreset.value)
    p.style_preset = STYLE_PRESET_KEY_MAP[s.stylePreset.value] ?? ''
  if (s.strength.enabled) p.strength = s.strength.value
  return p
}

const CTL = 'w-full px-2 py-1 rounded-lg text-xs bg-theme-bg border border-theme-border/60 text-theme-text focus:outline-none focus:ring-1 focus:ring-theme-border'

export default function AdvancedParams({
  modelId,
  onChange,
  showStrength,
  onStrengthEnabledChange,
  open,
}: {
  modelId: string
  onChange: (p: ImageParams) => void
  showStrength?: boolean
  onStrengthEnabledChange?: (enabled: boolean) => void
  open: boolean
}) {
  const [s, setS] = useState<AdvancedState>(() => initialAdvanced(modelId))
  const isFlux = modelId === 'flux'

  function update<K extends keyof AdvancedState>(key: K, patch: Partial<AdvancedState[K]>) {
    const next = { ...s, [key]: { ...s[key], ...patch } } as AdvancedState
    setS(next)
    onChange(deriveParams(next))
    if (key === 'strength' && 'enabled' in patch && onStrengthEnabledChange) {
      onStrengthEnabledChange(!!(patch as Partial<ParamState<number>>).enabled)
    }
  }

  useEffect(() => {
    if (!showStrength) return
    setS((prev) => {
      if (prev.strength.enabled) return prev
      const next = { ...prev, strength: { ...prev.strength, enabled: true } } as AdvancedState
      onChange(deriveParams(next))
      onStrengthEnabledChange?.(true)
      return next
    })
  }, [showStrength, onChange, onStrengthEnabledChange])

  const rowCls = (enabled: boolean) =>
    `pl-5 space-y-1 transition-opacity ${enabled ? '' : 'opacity-40 pointer-events-none'}`

  if (!open) return null

  return (
    <div className="space-y-3.5 p-2.5 rounded-xl bg-theme-bg border border-theme-border/40">

      {/* Row 1: Aspect Ratio (Left) & Style (Right) */}
      <div className="grid grid-cols-2 gap-3">
        {/* Aspect Ratio */}
        <div className="space-y-1">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={s.aspectRatio.enabled}
              onChange={(e) => update('aspectRatio', { enabled: e.target.checked })}
              className="w-3.5 h-3.5 rounded accent-theme-brand" />
            <span className="text-xs font-semibold text-theme-text">Aspect Ratio</span>
          </label>
          <div className={rowCls(s.aspectRatio.enabled)}>
            <select value={s.aspectRatio.value}
              onChange={(e) => update('aspectRatio', { value: e.target.value })}
              className={CTL}>
              {Object.entries(RATIO_TO_SIZE).map(([r, sz]) => (
                <option key={r} value={r}>{r} — {sz.width}×{sz.height}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Style Preset */}
        <div className="space-y-1">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={s.stylePreset.enabled}
              onChange={(e) => update('stylePreset', { enabled: e.target.checked })}
              className="w-3.5 h-3.5 rounded accent-theme-brand" />
            <span className="text-xs font-semibold text-theme-text">Style</span>
          </label>
          <div className={rowCls(s.stylePreset.enabled)}>
            <select value={s.stylePreset.value}
              onChange={(e) => update('stylePreset', { value: e.target.value })}
              className={CTL}>
              <option value="">None</option>
              {Object.keys(STYLE_PRESET_KEY_MAP).map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Inference Steps */}
      <div className="space-y-1">
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={s.steps.enabled}
            onChange={(e) => update('steps', { enabled: e.target.checked })}
            className="w-3.5 h-3.5 rounded accent-theme-brand" />
          <span className="text-xs font-medium text-theme-text">Inference Steps</span>
          <span className="text-[10px] text-theme-text-muted font-normal">(4 – 50)</span>
        </label>
        <div className={rowCls(s.steps.enabled)}>
          <div className="flex items-center gap-2">
            <input type="range" min={4} max={50} value={s.steps.value}
              onChange={(e) => update('steps', { value: Number(e.target.value) })}
              className="flex-1 accent-theme-brand" />
            <span className="text-xs w-6 text-right tabular-nums text-theme-text-muted">{s.steps.value}</span>
          </div>
        </div>
      </div>

      {/* Guidance Scale */}
      <div className="space-y-1">
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={s.guidanceScale.enabled}
            onChange={(e) => update('guidanceScale', { enabled: e.target.checked })}
            className="w-3.5 h-3.5 rounded accent-theme-brand" />
          <span className="text-xs font-medium text-theme-text">Guidance Scale</span>
          <span className="text-[10px] text-theme-text-muted font-normal">(1.0 – 20.0)</span>
        </label>
        <div className={rowCls(s.guidanceScale.enabled)}>
          <div className="flex items-center gap-2">
            <input type="range" min={1} max={20} step={0.5} value={s.guidanceScale.value}
              onChange={(e) => update('guidanceScale', { value: Number(e.target.value) })}
              className="flex-1 accent-theme-brand" />
            <span className="text-xs w-8 text-right tabular-nums text-theme-text-muted">{s.guidanceScale.value}</span>
          </div>
          {isFlux && (
            <div className="text-[10px] text-amber-600 dark:text-amber-400">FLUX is guidance-free — this value is ignored</div>
          )}
        </div>
      </div>

      {/* Negative Prompt */}
      <div className="space-y-1">
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={s.negativePrompt.enabled}
            onChange={(e) => update('negativePrompt', { enabled: e.target.checked })}
            className="w-3.5 h-3.5 rounded accent-theme-brand" />
          <span className="text-xs font-medium text-theme-text">Negative Prompt</span>
        </label>
        <div className={rowCls(s.negativePrompt.enabled)}>
          <input type="text" value={s.negativePrompt.value}
            onChange={(e) => update('negativePrompt', { value: e.target.value })}
            placeholder="avoid: blurry, cartoon, text…"
            className={CTL} />
        </div>
      </div>

      {/* Strength — only shown when an init image is attached */}
      {showStrength && (
        <div className="space-y-1">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={s.strength.enabled}
              onChange={(e) => update('strength', { enabled: e.target.checked })}
              className="w-3.5 h-3.5 rounded accent-theme-brand" />
            <span className="text-xs font-medium text-theme-text">Strength</span>
            <span className="text-[10px] text-theme-text-muted font-normal">(0.1 – 1.0)</span>
          </label>
          <div className={rowCls(s.strength.enabled)}>
            <div className="flex items-center gap-2">
              <input type="range" min={0.1} max={1.0} step={0.05} value={s.strength.value}
                onChange={(e) => update('strength', { value: Number(e.target.value) })}
                className="flex-1 accent-theme-brand" />
              <span className="text-xs w-8 text-right tabular-nums text-theme-text-muted">{s.strength.value.toFixed(2)}</span>
            </div>
            <div className="text-[10px] text-theme-text-muted">lower = stay closer to source image</div>
          </div>
        </div>
      )}

    </div>
  )
}
