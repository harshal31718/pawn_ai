import type { ImageParams } from '../api/client'
import { STYLE_PRESET_KEY_MAP, SUBJECT_TYPE_KEY_MAP, type AdvancedState } from '../types'

export type { AdvancedState, ParamState } from '../types'

// Q1.4: max value for a 🎲 randomize click. Bounded well under 2^32 so it's
// always representable as a JS safe integer and fits comfortably as a
// Postgres int4 job-params field without any range-check surprises.
export const MAX_RANDOM_SEED = 2_147_483_647

// SDXL-native ~1024²-area buckets (Q1.1). Off-bucket sizes (the old SD1.5-era
// 512/576/768 values) are the classic cause of half-generated/deformed bodies.
// All values are multiples of 16, so the same table satisfies FLUX's flexible-
// but-/16-rounded architecture too.
const SDXL_NATIVE_BUCKETS: Record<string, { width: number; height: number }> = {
  '1:1': { width: 1024, height: 1024 },
  '3:4': { width: 896, height: 1152 },
  '4:5': { width: 832, height: 1216 },
  '4:3': { width: 1152, height: 896 },
  '16:9': { width: 1344, height: 768 },
  '9:16': { width: 768, height: 1344 },
}

/**
 * Per-model advanced-params behavior: which fields are shown at all, their
 * defaults/ranges/hints, and how state derives into the wire-format
 * ImageParams. One base class holds everything that's genuinely shared
 * across models; each model subclass overrides only what's actually
 * different for it — visibility flags, defaults, hint text — so a field that
 * doesn't apply to a model (e.g. FLUX's fixed step count) is a one-line
 * override here instead of an `isFlux` check scattered through the component.
 */
export abstract class ModelAdvancedConfig {
  abstract readonly modelId: string
  abstract readonly defaultSteps: number
  abstract readonly defaultGuidance: number

  readonly resolutionBuckets: Record<string, { width: number; height: number }> = SDXL_NATIVE_BUCKETS
  readonly stepsRange = { min: 4, max: 50 }
  readonly stepsHint: string | null = '20–40 recommended'
  readonly guidanceRange = { min: 1, max: 20, step: 0.5 }

  // Field visibility — base default is "show everything"; subclasses turn
  // off what doesn't apply to them.
  readonly showSteps: boolean = true
  readonly showGuidance: boolean = true
  readonly showNegativePrompt: boolean = true

  guidanceHint(): string | null {
    return null
  }

  // Whether guidanceHint() is a warning (value being ignored) vs. a plain
  // informational note — drives the hint's styling, so the component never
  // needs its own per-model color check.
  readonly guidanceHintIsWarning: boolean = false

  initialAdvanced(forcedSeed?: number): AdvancedState {
    return {
      aspectRatio: { enabled: false, value: '3:4' },
      steps: { enabled: false, value: this.defaultSteps },
      guidanceScale: { enabled: false, value: this.defaultGuidance },
      negativePrompt: { enabled: false, value: '' },
      stylePreset: { enabled: false, value: '' },
      strength: { enabled: false, value: 0.6 },
      seed: forcedSeed !== undefined
        ? { enabled: true, value: forcedSeed }
        : { enabled: false, value: 0 },
      // Q3.3b: orthogonal subject-type axis. "Portrait" is the existing
      // default assumption -- no vocabulary injected -- so starting disabled
      // with that value is a true no-op until the user picks something else.
      // Stores the LABEL (matching stylePreset's convention below), not the
      // key -- resolved through SUBJECT_TYPE_KEY_MAP at derive time.
      subjectType: { enabled: false, value: 'Portrait' },
    }
  }

  deriveParams(s: AdvancedState): ImageParams {
    const p: ImageParams = {}
    if (s.aspectRatio.enabled && this.resolutionBuckets[s.aspectRatio.value]) {
      const sz = this.resolutionBuckets[s.aspectRatio.value]
      p.width = sz.width
      p.height = sz.height
    }
    if (this.showSteps && s.steps.enabled) p.num_inference_steps = s.steps.value
    if (this.showGuidance && s.guidanceScale.enabled) p.guidance_scale = s.guidanceScale.value
    // Q1.4 honesty rule: never derive negative_prompt for a model that
    // doesn't show the field, even if state carries a stale enabled value
    // from somewhere (e.g. switching models without a remount).
    if (this.showNegativePrompt && s.negativePrompt.enabled && s.negativePrompt.value.trim())
      p.negative_prompt = s.negativePrompt.value.trim()
    if (s.stylePreset.enabled && s.stylePreset.value)
      p.style_preset = STYLE_PRESET_KEY_MAP[s.stylePreset.value] ?? ''
    if (s.strength.enabled) p.strength = s.strength.value
    if (s.seed.enabled) p.seed = s.seed.value
    if (s.subjectType.enabled && s.subjectType.value)
      p.subject_type = SUBJECT_TYPE_KEY_MAP[s.subjectType.value] ?? ''
    return p
  }
}

// Per-model floor: SDXL wants ~30 steps for good quality (its notebook default).
// Q1.3: SDXL's photoreal sweet spot is 3-5 CFG, not the old 7.5 (matches the
// notebooks' own tuned default).
export class SdxlAdvancedConfig extends ModelAdvancedConfig {
  readonly modelId = 'sdxl'
  readonly defaultSteps = 30
  readonly defaultGuidance = 5

  guidanceHint() {
    return '3–5 = more photoreal'
  }
}

// FLUX.1-schnell is a guidance-distilled model: it's fixed to ~4 inference
// steps (more steps gain nothing — there's no "recommended range" to expose,
// unlike SDXL) and its pipeline call hardcodes guidance_scale=0.0 regardless
// of what's sent, so CFG has no effect and negative_prompt isn't even an
// accepted parameter. All three of those UI controls are hidden entirely
// here rather than shown-but-inert.
export class FluxAdvancedConfig extends ModelAdvancedConfig {
  readonly modelId = 'flux'
  readonly defaultSteps = 4
  readonly defaultGuidance = 0
  readonly showSteps = false
  readonly showNegativePrompt = false
  readonly guidanceHintIsWarning = true

  guidanceHint() {
    return 'FLUX is guidance-free — this value is ignored'
  }
}

const CONFIGS: Record<string, ModelAdvancedConfig> = {
  sdxl: new SdxlAdvancedConfig(),
  flux: new FluxAdvancedConfig(),
}

export function configFor(modelId: string): ModelAdvancedConfig {
  return CONFIGS[modelId] ?? CONFIGS.sdxl
}

// Backward-compatible per-model lookup tables, now sourced from the config
// classes above instead of being a second, independently-maintained copy.
export const DEFAULT_STEPS: Record<string, number> = Object.fromEntries(
  Object.entries(CONFIGS).map(([id, cfg]) => [id, cfg.defaultSteps]),
)
export const DEFAULT_GUIDANCE: Record<string, number> = Object.fromEntries(
  Object.entries(CONFIGS).map(([id, cfg]) => [id, cfg.defaultGuidance]),
)
