import { useState, useEffect } from 'react'
import type { ImageParams } from '../api/client'
import { STYLE_PRESET_KEY_MAP, SUBJECT_TYPE_KEY_MAP } from '../types'
import {
  configFor,
  MAX_RANDOM_SEED,
  DEFAULT_STEPS,
  DEFAULT_GUIDANCE,
  type AdvancedState,
} from './advancedParamsConfig'

export type { AdvancedState } from './advancedParamsConfig'
export { DEFAULT_STEPS, DEFAULT_GUIDANCE }

export function initialAdvanced(modelId: string, forcedSeed?: number): AdvancedState {
  return configFor(modelId).initialAdvanced(forcedSeed)
}

export const INITIAL_ADVANCED: AdvancedState = initialAdvanced('sdxl')

export function deriveParams(s: AdvancedState, modelId: string = 'sdxl'): ImageParams {
  return configFor(modelId).deriveParams(s)
}

const CTL = 'w-full px-2 py-1 rounded-lg text-xs bg-theme-bg border border-theme-border/60 text-theme-text focus:outline-none focus:ring-1 focus:ring-theme-border'

export default function AdvancedParams({
  modelId,
  onChange,
  showStrength,
  onStrengthEnabledChange,
  open,
  forcedSeed,
}: {
  modelId: string
  onChange: (p: ImageParams) => void
  showStrength?: boolean
  onStrengthEnabledChange?: (enabled: boolean) => void
  open: boolean
  // Q1.4 "reuse seed": pass { value, nonce } from a Generations row's Reuse
  // action. `nonce` (not just `value`) drives the effect below, so reusing
  // the SAME seed value twice in a row still re-applies it.
  forcedSeed?: { value: number; nonce: number }
}) {
  const config = configFor(modelId)
  const [s, setS] = useState<AdvancedState>(() => config.initialAdvanced())

  useEffect(() => {
    if (forcedSeed === undefined) return
    setS((prev) => {
      const next = { ...prev, seed: { enabled: true, value: forcedSeed.value } } as AdvancedState
      onChange(config.deriveParams(next))
      return next
    })
  }, [forcedSeed?.nonce, forcedSeed?.value, onChange, config])

  function update<K extends keyof AdvancedState>(key: K, patch: Partial<AdvancedState[K]>) {
    const next = { ...s, [key]: { ...s[key], ...patch } } as AdvancedState
    setS(next)
    onChange(config.deriveParams(next))
    if (key === 'strength' && 'enabled' in patch && onStrengthEnabledChange) {
      onStrengthEnabledChange(!!(patch as Partial<{ enabled: boolean }>).enabled)
    }
  }

  useEffect(() => {
    if (!showStrength) return
    setS((prev) => {
      if (prev.strength.enabled) return prev
      const next = { ...prev, strength: { ...prev.strength, enabled: true } } as AdvancedState
      onChange(config.deriveParams(next))
      onStrengthEnabledChange?.(true)
      return next
    })
  }, [showStrength, onChange, onStrengthEnabledChange, config])

  const rowCls = (enabled: boolean) =>
    `pl-5 space-y-1 transition-opacity ${enabled ? '' : 'opacity-40 pointer-events-none'}`

  if (!open) return null

  const guidanceHint = config.guidanceHint()

  return (
    <div className="space-y-3.5 p-2.5 rounded-xl bg-theme-bg border border-theme-border/40">

      {/* Row 1: Aspect Ratio, Style, Subject Type */}
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
              {Object.entries(config.resolutionBuckets).map(([r, sz]) => (
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

        {/* Subject Type — Q3.3b: orthogonal to style, composes with it */}
        <div className="space-y-1 col-span-2">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={s.subjectType.enabled}
              onChange={(e) => update('subjectType', { enabled: e.target.checked })}
              className="w-3.5 h-3.5 rounded accent-theme-brand" />
            <span className="text-xs font-semibold text-theme-text">Subject</span>
          </label>
          <div className={rowCls(s.subjectType.enabled)}>
            <select value={s.subjectType.value}
              onChange={(e) => update('subjectType', { value: e.target.value })}
              className={CTL}>
              {Object.keys(SUBJECT_TYPE_KEY_MAP).map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Inference Steps — hidden entirely for models that don't have a
          meaningful adjustable range (e.g. FLUX's fixed ~4-step distillation) */}
      {config.showSteps && (
        <div className="space-y-1">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={s.steps.enabled}
              onChange={(e) => update('steps', { enabled: e.target.checked })}
              className="w-3.5 h-3.5 rounded accent-theme-brand" />
            <span className="text-xs font-medium text-theme-text">Inference Steps</span>
            <span className="text-[10px] text-theme-text-muted font-normal">
              ({config.stepsRange.min} – {config.stepsRange.max}{config.stepsHint ? `, ${config.stepsHint}` : ''})
            </span>
          </label>
          <div className={rowCls(s.steps.enabled)}>
            <div className="flex items-center gap-2">
              <input type="range" min={config.stepsRange.min} max={config.stepsRange.max} value={s.steps.value}
                onChange={(e) => update('steps', { value: Number(e.target.value) })}
                className="flex-1 accent-theme-brand" />
              <span className="text-xs w-6 text-right tabular-nums text-theme-text-muted">{s.steps.value}</span>
            </div>
          </div>
        </div>
      )}

      {/* Guidance Scale */}
      {config.showGuidance && (
        <div className="space-y-1">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={s.guidanceScale.enabled}
              onChange={(e) => update('guidanceScale', { enabled: e.target.checked })}
              className="w-3.5 h-3.5 rounded accent-theme-brand" />
            <span className="text-xs font-medium text-theme-text">Guidance Scale</span>
            <span className="text-[10px] text-theme-text-muted font-normal">
              ({config.guidanceRange.min.toFixed(1)} – {config.guidanceRange.max.toFixed(1)})
            </span>
          </label>
          <div className={rowCls(s.guidanceScale.enabled)}>
            <div className="flex items-center gap-2">
              <input type="range" min={config.guidanceRange.min} max={config.guidanceRange.max}
                step={config.guidanceRange.step} value={s.guidanceScale.value}
                onChange={(e) => update('guidanceScale', { value: Number(e.target.value) })}
                className="flex-1 accent-theme-brand" />
              <span className="text-xs w-8 text-right tabular-nums text-theme-text-muted">{s.guidanceScale.value}</span>
            </div>
            {guidanceHint && (
              <div className={config.guidanceHintIsWarning
                ? 'text-[10px] text-amber-600 dark:text-amber-400'
                : 'text-[10px] text-theme-text-muted'}>
                {guidanceHint}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Negative Prompt — Q1.4 honesty rule: hidden for models whose
          pipeline call doesn't accept it at all (e.g. FLUX), instead of
          showing a field that silently does nothing. */}
      {config.showNegativePrompt && (
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
          <div className="text-[10px] text-theme-text-muted">
            a photoreal default negative is always added — anything here is appended to it
          </div>
        </div>
      )}

      {/* Seed — Q1.4: fixed seed for reproducible A/Bs, with a randomize action */}
      <div className="space-y-1">
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={s.seed.enabled}
            onChange={(e) => update('seed', { enabled: e.target.checked })}
            className="w-3.5 h-3.5 rounded accent-theme-brand" />
          <span className="text-xs font-medium text-theme-text">Seed</span>
        </label>
        <div className={rowCls(s.seed.enabled)}>
          <div className="flex items-center gap-2">
            <input type="number" min={0} max={MAX_RANDOM_SEED} value={s.seed.value}
              onChange={(e) => update('seed', { value: Math.max(0, Number(e.target.value) || 0) })}
              className={CTL} />
            <button type="button"
              title="Randomize seed"
              onClick={() => update('seed', { value: Math.floor(Math.random() * MAX_RANDOM_SEED) })}
              className="shrink-0 w-7 h-7 flex items-center justify-center rounded-lg border border-theme-border/60 text-sm hover:bg-theme-surface-hover cursor-pointer">
              🎲
            </button>
          </div>
          <div className="text-[10px] text-theme-text-muted">same prompt + seed = reproducible A/B</div>
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
