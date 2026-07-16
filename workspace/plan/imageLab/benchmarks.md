# imageLab — Fixed-Seed A/B Benchmark Set (Q1.5)

Defined per `phase_Q1_generation_fixes.md`'s Q1.5. This set is the regression
baseline for Q1's correctness fixes (Q1.1-Q1.4) and stays in use for Q2-Q4.

Run against a live warm SDXL session. Each prompt uses a fixed seed so the
same run is exactly reproducible via Q1.4's seed field / "reuse seed" action.

## Prompts + seeds

| # | Category | Prompt | Seed |
|---|---|---|---|
| 1 | Portrait | `a photorealistic portrait of an elderly fisherman, weathered face, deep wrinkles, sitting on a wooden dock at golden hour, shallow depth of field` | `100001` |
| 2 | Full-body | `a full-body shot of a woman in a red evening dress standing on a marble staircase, elegant pose, soft studio lighting` | `100002` |
| 3 | Landscape | `a sweeping mountain landscape at sunrise, mist in the valley, pine forest in the foreground, dramatic clouds` | `100003` |
| 4 | Object macro | `a macro photograph of a dew-covered spider web between two blades of grass, morning light, extreme detail` | `100004` |
| 5 | Low-light | `a dimly lit jazz bar interior, a saxophonist mid-performance on a small stage, warm amber lighting, smoky atmosphere` | `100005` |
| 6 | Group scene | `four friends laughing around a campfire at night, illuminated by firelight, forest background, candid moment` | `100006` |

## Fixed generation params for this benchmark

- Aspect ratio: 3:4 portrait (896×1152) for #1/#2, 16:9 (1344×768) for #3, 1:1
  (1024×1024) for #4/#5/#6 — one representative bucket per category, not
  every bucket × every prompt.
- Steps: 30 (SDXL default), CFG: 5 (SDXL default) — i.e. run with Advanced
  Params *disabled* except for aspect ratio + seed, so the benchmark measures
  the shipped defaults, not a hand-tuned outlier.
- Style preset: none, negative prompt: none — isolates the notebook/model
  fixes themselves from Q3's prompt-scaffolding work (out of scope until Q3).

## What to check per image

1. **No black/corrupt frame** (Q1.2's regression target).
2. **Full body/subject visible, no half-generated crops** (Q1.1's regression
   target) — most visible on #1 and #2.
3. **Visible sharpness/detail vs. a pre-Q1 baseline** (Q1.3's scheduler
   target) — most visible on #4 (macro detail) and #3 (landscape texture).
4. **Photorealism, not over-sharpened/oversaturated "AI-look"** (Q1.3's CFG
   target).
5. **Re-running the exact same prompt+seed produces the same image**
   (Q1.4's determinism target) — run each prompt twice, compare.

## Result log

Results get appended here (or referenced from `dev_log.md`) once run against
a real warm SDXL session. Not yet run — needs the user's own Kaggle account
and live GPU time (out of scope for an unattended session).

| Date | Run | # black frames / 6 | Notes |
|---|---|---|---|
| — | pre-Q1 baseline | — | not yet run |
| — | post-Q1 (Q1.1-Q1.4) | — | not yet run |
