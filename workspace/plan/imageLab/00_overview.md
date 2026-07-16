# imageLab — Quality & Features Plan (Overview)

**Status:** PLANNED. **Branch:** `dev`. **Folder:** `workspace/plan/imageLab/`
**Date:** 2026-07-15

## 1. Why this plan exists

User verdict on current output: **"results are not that good, don't look real, images have
flaws like half-generated."** Code audit (2026-07-15) found concrete, fixable causes — the
pipeline is architecturally sound (warm sessions, jobs, params all work); the *generation
recipe* inside the notebooks is what's weak. This folder = consolidated image plans + a
research-backed quality program executed entirely on the existing Kaggle pipeline.

## 2. Root-cause diagnosis (verified against code, mapped to fixes)

| Reported flaw | Verified cause in our code | Fix phase |
|---|---|---|
| Half-generated / cropped / deformed bodies | `AdvancedParams.tsx`'s `RATIO_TO_SIZE` uses **SD1.5-era sizes** (512×512, 1024×576, 576×1024, 768×576). SDXL is trained on ~1024²-area buckets — off-bucket sizes are the classic cause of exactly this artifact class | **Q1.1 (the headline fix)** |
| Random black/partial images | notebooks load fp16 (`torch_dtype=torch.float16`) with the **stock SDXL VAE**, which overflows fp16 (>65504 activations → inf/NaN → black/broken decodes) | Q1.2 |
| Soft/artifacty output | **no scheduler configured** (library default); DPM++ 2M Karras-class samplers with stabilizers are the community-proven recipe; steps/CFG defaults untuned per model | Q1.3 |
| "Doesn't look real" | model is **base SDXL 1.0** — mediocre photorealism by 2026 standards; photoreal fine-tunes (Juggernaut XL, RealVisXL) are drop-in same-architecture upgrades; FLUX-schnell capped by 4-step distillation | Q2 |
| Flat/generic look | no default negative prompt, no photoreal prompt scaffolding, style presets are thin suffixes | Q3 |
| Broken faces/hands at distance | no face-detail pass, no refiner/two-pass, no FreeU | Q4 |

## 3. File index

| File | What |
|---|---|
| `00_overview.md` | this file |
| `01_research_quality.md` | web-research reference: checkpoints, settings, fixes, prompting (+sources) |
| `open_items.md` | pre-existing open items (FLUX OOM merge, live smoke tests, prod-gated, stop hypotheses) — moved from `plan/plan_imagelab_open_items.md` |
| `phase_Q1_generation_fixes.md` | correctness: resolution buckets, fp16 VAE fix, scheduler, per-model defaults, seed |
| `phase_Q2_realism_models.md` | photoreal checkpoints as new model rows (Juggernaut/RealVis), FLUX guidance |
| `phase_Q3_prompting_presets.md` | LLM prompt enhancer, negative defaults/embeddings, preset rework |
| `phase_Q4_detail_post.md` | two-pass hires fix, face detailer, refiner, FreeU — the polish layer |
| `phase_G1_generations_management.md` | feature (not quality): delete/edit/reorder generations in the Generations tab, requested 2026-07-15 |

Related but living elsewhere: **F-1 chat image-gen tool** in `plan/chat/` (feature,
not quality — unchanged).

## 4. Ground rules

- All work on the existing Kaggle pipeline — no new infra, no new tables (Q-phases touch
  notebooks, `image_models.py` rows, `AdvancedParams`/composer defaults, and add small
  params only). Additive; dev stays working; imageLab prod path respected.
- Standard gates: template tests + full backend suite + `npm run build`; build-step skill
  per numbered step; tracker/current_state/dev_log updated per step.
- Every quality change lands with a **before/after A/B on a fixed prompt+seed set**
  (defined in Q1.5) recorded in dev_log — no vibes-only "improvements."
- Order: **Q1 → Q2 → Q3 → Q4**. Q1 alone should eliminate the reported flaws; Q2 delivers
  the realism jump; Q3/Q4 are refinement.

## 5. Success criteria

A portrait prompt at 9:16 produces a full, anatomically-correct person (no crops/halves),
zero black images across 20 consecutive generations, photorealism competitive with
Civitai-class showcase output on Juggernaut/RealVis rows, and a one-click "Enhance"
prompt upgrade — all on the same free Kaggle T4s.
