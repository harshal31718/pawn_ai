# Q0 — Image Quality Research Reference

**Status:** REFERENCE (no code). Compiled 2026-07-15 from web research. All of it applies
to our stack: Diffusers pipelines, fp16, Kaggle T4s, warm serve-loop notebooks.

---

## 1. Resolution buckets (the half-generated-body fix)

SDXL was trained on ~1024²-area resolution buckets. Generating off-bucket (especially
512-class sizes) yields cropped subjects, duplicated/half bodies, and mush — exactly our
reported flaws. Community-standard buckets to adopt:

| Aspect | Size | Use |
|---|---|---|
| 1:1 | 1024×1024 | default |
| 3:4 | 896×1152 | portrait (RealVis-recommended) |
| 4:5-ish | 832×1216 | portrait (Juggernaut-recommended; matches training data) |
| 4:3 | 1152×896 | landscape |
| 16:9 | 1344×768 | wide |
| 9:16 | 768×1344 | vertical/reel |

FLUX is resolution-flexible (any multiple-of-16 up to ~2MP) but benefits from the same
sane presets. T4 note: 1024²-class fp16 SDXL fits a single T4 fine; expect ~1.5–2× the
512² step time — acceptable, and warm sessions absorb it.

## 2. fp16 VAE overflow (the black/partial-image fix)

The stock SDXL VAE overflows fp16 during decode (activations >65504 → inf/NaN → black or
corrupted images — intermittent, worse at larger sizes). Standard fix, zero quality cost:
load **`madebyollin/sdxl-vae-fp16-fix`** as the pipeline's VAE (better than
`no_half_vae`/fp32-upcast, which costs VRAM and detail). One `AutoencoderKL.from_pretrained`
line in the SDXL notebooks; weights ~335 MB (add to the weights dataset or allow this one
small runtime download).

## 3. Scheduler + steps + CFG (the sharpness/naturalness recipe)

- Community-proven for SDXL photorealism: **DPM++ 2M (SDE) with Karras sigmas**.
  Diffusers: `DPMSolverMultistepScheduler.from_config(pipe.scheduler.config,
  use_karras_sigmas=True, algorithm_type="sde-dpmsolver++")` — and note the documented
  instability fix for <50 steps: `use_karras_sigmas=True` (or `lu_lambdas=True`) plus
  `euler_at_final=True` for uniform-step solvers.
- Photoreal settings consensus (Juggernaut/RealVis guides): **steps 30–40, CFG 3–7 with
  low CFG (3–5) leaning photoreal**; waxy skin / oversaturation → drop CFG to 3–5, cap
  steps ~30. Our current UI slider defaults (SDXL 30 via `initialAdvanced`) are close but
  CFG default and ranges need re-centering (SDXL default CFG in our notebook is whatever
  Diffusers defaults to = 5.0 — acceptable; expose 3–7 as the recommended band).
- FLUX-schnell: steps 1–4 (4 best), guidance fixed 0 (already correct in our notebook);
  realism comes from prompting (below), not settings.

## 4. Photoreal checkpoints (the realism jump)

Drop-in SDXL-architecture fine-tunes — same pipeline class, same VRAM, just different
weights (→ new `image_models.py` rows + Kaggle weight datasets):

| Model | Notes | Recommended recipe |
|---|---|---|
| **Juggernaut XL** (v10 "Ragnarok"-class) | community's go-to photoreal all-rounder; skin texture, lighting, anatomy | 832×1216, DPM++ 2M (SDE) Karras, 30–40 steps, CFG 3–7 (photoreal at 3–5) |
| **RealVisXL V5.0** | humans specialist; strongest skin/hair detail | 896×1152, DPM++ 3M SDE Karras, 30 steps, CFG 6 |

Licensing/access: both are on Civitai/HF; verify redistribution terms when publishing
private Kaggle weight datasets (per-user private datasets = fine for personal BYOK use).
FLUX.1-dev (better than schnell) is non-commercial-licensed and 20–30 steps (slow on T4)
— noted as optional row, not default.

## 5. Prompting (biggest free win)

- **SDXL photoreal scaffold:** subject + camera/lens language ("85mm portrait, shallow
  depth of field"), lighting ("golden hour rim light"), film/texture words ("skin pores,
  film grain"). Default negative prompt worth shipping: variants of
  "cartoon, painting, illustration, 3d render, plastic skin, deformed, extra fingers,
  bad anatomy, blurry, watermark, text".
- **Negative embeddings** (textual inversions like the unaesthetic/negative-XL family) are
  a cheap quality boost — load via `pipe.load_textual_inversion`, reference in the negative
  prompt. Optional (Q3), needs dataset hosting like any weights.
- **FLUX prompting is different:** natural-language sentences, no keyword soup, no negative
  prompt (CFG 0 ignores it — our UI should HIDE negative prompt for FLUX instead of
  accepting and silently dropping it); realism descriptors ("amateur photo, natural skin
  texture, film grain") matter; frame as Subject → Action → Environment → Lighting → Style.
- **LLM prompt enhancer** (Q3): PAWN already has `normalize.chat_complete` — a per-model
  system prompt turns "a girl in a café" into a full photoreal scaffold.

## 6. Detail/polish techniques (Q4 menu, all Diffusers-native, T4-viable)

- **Two-pass hires fix:** generate at bucket → upscale latents/image 1.5–2× → img2img pass
  at low strength (0.25–0.4) — sharper detail, fixes soft output. Uses the existing img2img
  plumbing (IR-1..IR-3) — mostly notebook-side.
- **Face detailer (ADetailer-style):** detect faces (small detector: YOLO-face or
  mediapipe), crop → img2img the crop at higher res → paste back. Fixes broken
  faces-at-distance, the #1 realism killer in full-body shots.
- **Refiner:** SDXL refiner model as optional second stage (adds VRAM+time on T4;
  fine-tunes often don't need it — LOW priority vs face detailer).
- **FreeU:** free quality knob, one line (`pipe.enable_freeu(...)`), no weights; worth an
  A/B — results are model-dependent.

## 7. Sources

- Buckets/settings/checkpoints: https://www.rundiffusion.com/juggernaut-xl-rundiffusion-guide ·
  https://sozee.ai/resources/juggernaut-xl-photorealism-stable-diffusion/ ·
  https://insiderllm.com/guides/best-photorealism-checkpoints-local-image-generation/ ·
  https://www.qwe.edu.pl/tutorial/stable-diffusion-best-models-realistic-images/ ·
  https://www.aiarty.com/stable-diffusion-guide/best-stable-diffusion-models.htm
- fp16 VAE: https://huggingface.co/madebyollin/sdxl-vae-fp16-fix ·
  https://dev.to/elise_moreau/the-sdxl-vae-overflow-that-decoded-black-images-in-fp16-46g6
- Scheduler stability (<50 steps, karras/lu_lambdas/euler_at_final):
  https://huggingface.co/docs/diffusers/api/pipelines/stable_diffusion/stable_diffusion_xl ·
  diffusers PR #5541 (DPM++ stabilization)
- FLUX prompting: https://skywork.ai/blog/flux-prompting-ultimate-guide-flux1-dev-schnell/ ·
  https://www.promptlabhub.com/cheatsheet/flux ·
  https://www.stablediffusiontutorials.com/2025/04/flux-schnell-dev-pro.html
