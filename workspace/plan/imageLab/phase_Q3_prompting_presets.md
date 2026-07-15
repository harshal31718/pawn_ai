# Phase Q3 — Prompting: Enhancer, Negatives, Preset Rework

**Goal:** the biggest free quality win — turn terse user prompts into photoreal-grade
prompts automatically, ship sane negative defaults, and rebuild style presets on the
research findings. Everything here is prompt-plumbing; no new weights except optional
negative embeddings.

**Read first:** `01_research_quality.md` §5, `routes/generate.py` (`STYLE_SUFFIXES`),
`core/normalize.py` (LLM plumbing), videoLab v2 `phase_P6_orchestration_quality.md` §P6.1
(same enhancer design — imageLab lands it first, videoLab reuses).

**Branch:** `dev`. Steps Q3.1–Q3.4.

---

## Q3.1 — LLM prompt enhancer

**Files:** new `backend/app/core/image_prompting.py`, `routes/generate.py`,
`frontend` composer toggle, tests.

- `enhance(prompt, model_row, style_preset) -> {prompt, negative}` via
  `normalize.chat_complete` (fast tier, absolute rule: normalize only). Per-model system
  prompts stored on the registry row (`prompt_style` field):
  - SDXL-family: keyword-rich scaffold — camera/lens, lighting, texture, film words.
  - FLUX: natural-language sentences, realism descriptors, NO negative.
- UI: "✨ Enhance" toggle in the composer (default ON), enhanced prompt shown editable
  before submit (never a black box); original + enhanced both stored in job params.
- Failure = fall through to raw prompt; never blocks generation. Works for both cold and
  warm paths (enhancement happens route-side before job insert — notebooks unchanged).

**Tests:** per-model scaffold selection, compose order with presets, LLM-failure
fallthrough, both-prompts-stored.

## Q3.2 — Default negatives (SDXL-family)

**Files:** `image_models.py` rows (`default_negative` field), `routes/generate.py` (merge
logic: default + user negative concatenated unless user opts out), UI hint, tests.

- Ship the research-backed default: "cartoon, painting, illustration, 3d render, plastic
  skin, deformed hands, extra fingers, bad anatomy, blurry, watermark, text" (tuned per
  row — Juggernaut/RealVis guides have their own recommendations; put those on their rows).
- FLUX rows: `default_negative = None` + field hidden (Q1.4).

**Tests:** merge logic matrix (default only / user only / both / opt-out).

## Q3.3 — Style presets rebuilt (imageLab's mini preset registry)

**Files:** `data/registry/image_presets.json` (new — mirrors videoLab v2 P4's design at
smaller scale), `routes/generate.py` (replace the hardcoded `STYLE_SUFFIXES` dict with
registry load; keep old keys working), composer chips UI, tests.

- Categories: style (photoreal, cinematic, analog film, studio product, golden hour,
  editorial), look (b&w, warm, moody), plus per-preset optional negative additions and
  per-model overrides (a preset can carry FLUX-phrasing + SDXL-phrasing variants).
- 15–20 presets authored from the research; calibrated on the Q1.5 benchmark set.

**Tests:** registry schema validation, per-model variant selection, legacy key
compatibility.

## Q3.4 — Optional: negative embeddings (decision + spike)

- Textual-inversion negatives (unaesthetic/negative-XL family) via
  `pipe.load_textual_inversion` — cheap boost but adds weights hosting + notebook change.
  Run as a SPIKE on one embedding: A/B on the benchmark set; adopt only on a clear win
  (record verdict here). If adopted: embeddings ride the model's weights dataset, one
  notebook line, `default_negative` references the trigger token.

---

## Risks

| Risk | Mitigation |
|---|---|
| Enhancer changes user intent | editable-before-submit UI + toggle + original stored |
| LLM latency on every gen | fast-tier model, ~1–2 s; toggle off = zero cost |
| Preset/negative soup degrades FLUX | per-model variants; FLUX gets natural-language phrasing only |
