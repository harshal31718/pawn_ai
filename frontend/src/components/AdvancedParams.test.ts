import { describe, it, expect } from 'vitest'
import { initialAdvanced, deriveParams, DEFAULT_STEPS, DEFAULT_GUIDANCE } from './AdvancedParams'

describe('Q1.1 — SDXL-native resolution buckets', () => {
  it('defaults aspect ratio to 3:4 portrait, not the old 1:1 square', () => {
    const s = initialAdvanced('sdxl')
    expect(s.aspectRatio.value).toBe('3:4')
  })

  it('derives the new 3:4 bucket size (896x1152), not the old SD1.5-era size', () => {
    const s = initialAdvanced('sdxl')
    s.aspectRatio.enabled = true
    const params = deriveParams(s)
    expect(params.width).toBe(896)
    expect(params.height).toBe(1152)
  })

  it('exposes all six SDXL-native buckets with /16-aligned dimensions', () => {
    const s = initialAdvanced('sdxl')
    s.aspectRatio.enabled = true
    const sizes: Record<string, { width: number; height: number }> = {}
    for (const ratio of ['1:1', '3:4', '4:5', '4:3', '16:9', '9:16']) {
      s.aspectRatio.value = ratio
      const p = deriveParams(s)
      sizes[ratio] = { width: p.width!, height: p.height! }
    }
    expect(sizes).toEqual({
      '1:1': { width: 1024, height: 1024 },
      '3:4': { width: 896, height: 1152 },
      '4:5': { width: 832, height: 1216 },
      '4:3': { width: 1152, height: 896 },
      '16:9': { width: 1344, height: 768 },
      '9:16': { width: 768, height: 1344 },
    })
    for (const { width, height } of Object.values(sizes)) {
      expect(width % 16).toBe(0)
      expect(height % 16).toBe(0)
    }
  })

  it('keeps model-aware step defaults unrelated to the bucket change', () => {
    expect(DEFAULT_STEPS.sdxl).toBe(30)
    expect(DEFAULT_STEPS.flux).toBe(4)
  })

  it('resolves buckets per-model, like initialAdvanced, not from one shared global', () => {
    const s = initialAdvanced('flux')
    s.aspectRatio.enabled = true
    s.aspectRatio.value = '9:16'
    const params = deriveParams(s, 'flux')
    expect(params.width).toBe(768)
    expect(params.height).toBe(1344)
  })
})

describe('Q1.3 — scheduler + tuned defaults', () => {
  it('SDXL guidance default is 5 (photoreal sweet spot), not the old 7.5', () => {
    const s = initialAdvanced('sdxl')
    expect(s.guidanceScale.value).toBe(5)
  })

  it('SDXL guidance derives to 5 when enabled', () => {
    const s = initialAdvanced('sdxl')
    s.guidanceScale.enabled = true
    const params = deriveParams(s, 'sdxl')
    expect(params.guidance_scale).toBe(5)
  })

  it('exposes DEFAULT_GUIDANCE per-model, mirroring DEFAULT_STEPS', () => {
    expect(DEFAULT_GUIDANCE.sdxl).toBe(5)
    expect(DEFAULT_GUIDANCE.flux).toBe(0)
  })
})

describe('Q1.4 — seed control + FLUX negative-prompt honesty', () => {
  it('seed is disabled with value 0 by default', () => {
    const s = initialAdvanced('sdxl')
    expect(s.seed.enabled).toBe(false)
    expect(s.seed.value).toBe(0)
  })

  it('a forced seed (reuse-seed) is pre-enabled with the given value', () => {
    const s = initialAdvanced('sdxl', 987654321)
    expect(s.seed.enabled).toBe(true)
    expect(s.seed.value).toBe(987654321)
  })

  it('derives seed into params only when enabled', () => {
    const s = initialAdvanced('sdxl')
    expect(deriveParams(s, 'sdxl').seed).toBeUndefined()
    s.seed.enabled = true
    s.seed.value = 42
    expect(deriveParams(s, 'sdxl').seed).toBe(42)
  })

  it('never derives negative_prompt for FLUX, even if state carries a stale enabled value', () => {
    const s = initialAdvanced('flux')
    s.negativePrompt.enabled = true
    s.negativePrompt.value = 'blurry'
    expect(deriveParams(s, 'flux').negative_prompt).toBeUndefined()
  })

  it('still derives negative_prompt normally for SDXL', () => {
    const s = initialAdvanced('sdxl')
    s.negativePrompt.enabled = true
    s.negativePrompt.value = 'blurry'
    expect(deriveParams(s, 'sdxl').negative_prompt).toBe('blurry')
  })
})
