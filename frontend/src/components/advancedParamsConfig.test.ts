import { describe, it, expect } from 'vitest'
import { configFor, SdxlAdvancedConfig, FluxAdvancedConfig, ModelAdvancedConfig } from './advancedParamsConfig'

describe('per-model advanced-params config (base class + subclasses)', () => {
  it('configFor resolves the correct subclass per model, falling back to SDXL for unknown ids', () => {
    expect(configFor('sdxl')).toBeInstanceOf(SdxlAdvancedConfig)
    expect(configFor('flux')).toBeInstanceOf(FluxAdvancedConfig)
    expect(configFor('unknown-model-id')).toBeInstanceOf(SdxlAdvancedConfig)
  })

  it('both subclasses extend the shared base class', () => {
    expect(configFor('sdxl')).toBeInstanceOf(ModelAdvancedConfig)
    expect(configFor('flux')).toBeInstanceOf(ModelAdvancedConfig)
  })

  it('FLUX hides the Inference Steps control entirely — it is fixed-distilled, not tunable', () => {
    expect(configFor('flux').showSteps).toBe(false)
    expect(configFor('sdxl').showSteps).toBe(true)
  })

  it('FLUX hides Negative Prompt (Q1.4 honesty rule) and shows a guidance warning hint', () => {
    const flux = configFor('flux')
    expect(flux.showNegativePrompt).toBe(false)
    expect(flux.guidanceHint()).toMatch(/guidance-free/i)
    expect(flux.guidanceHintIsWarning).toBe(true)
  })

  it('SDXL shows every field and a plain (non-warning) photoreal hint', () => {
    const sdxl = configFor('sdxl')
    expect(sdxl.showSteps).toBe(true)
    expect(sdxl.showGuidance).toBe(true)
    expect(sdxl.showNegativePrompt).toBe(true)
    expect(sdxl.guidanceHint()).toMatch(/photoreal/i)
    expect(sdxl.guidanceHintIsWarning).toBe(false)
  })

  it("deriveParams never emits num_inference_steps for FLUX, even if state carries a stale enabled value", () => {
    const flux = configFor('flux')
    const s = flux.initialAdvanced()
    s.steps.enabled = true
    s.steps.value = 20
    expect(flux.deriveParams(s).num_inference_steps).toBeUndefined()
  })

  it('deriveParams still emits num_inference_steps normally for SDXL', () => {
    const sdxl = configFor('sdxl')
    const s = sdxl.initialAdvanced()
    s.steps.enabled = true
    s.steps.value = 25
    expect(sdxl.deriveParams(s).num_inference_steps).toBe(25)
  })

  it('each subclass carries its own default steps/guidance', () => {
    expect(configFor('sdxl').defaultSteps).toBe(30)
    expect(configFor('sdxl').defaultGuidance).toBe(5)
    expect(configFor('flux').defaultSteps).toBe(4)
    expect(configFor('flux').defaultGuidance).toBe(0)
  })
})
