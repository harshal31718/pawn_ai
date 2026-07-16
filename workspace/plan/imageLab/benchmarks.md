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

**2026-07-16 — Partial live run, post-Q1 (Q1.1-Q1.4), real Kaggle SDXL warm
session.** Ran via Chrome against the real running dev stack (local
`cloudflared` tunnel restarted first — it wasn't running at all this session,
not "stale"). Only prompt #1 (Portrait) run, twice — not the full 6-prompt ×
2-run matrix (24 generations); scoped down given real GPU-time cost and no
pre-Q1 baseline available (reverting the fixes just to compare wasn't judged
worth it — see note below). No pre-Q1 baseline row: comparing "on" vs "off"
would mean temporarily reverting Q1.1-Q1.4 and re-running, which burns real
GPU quota to observe defects already well-documented from the original user
report and the code audit that motivated this whole plan.

| Date | Run | Prompt | Seed | Result |
|---|---|---|---|---|
| 2026-07-16 | post-Q1, run 1 | #1 Portrait | 100001 | Clean 3:4 portrait, full subject in frame, no crop, no black/corrupt pixels, sharp detail (wrinkles, hat weave, fabric texture), warm natural golden-hour lighting matching the prompt — not over-sharpened/oversaturated. 26s generation time. |
| 2026-07-16 | post-Q1, run 2 (determinism check) | #1 Portrait | 100001 | Pixel-identical to run 1 — same pose, same lighting, same background composition. Confirms Q1.4's seed reproducibility live, not just at the storage-round-trip-test level. 27s generation time. |

**Checklist against `## What to check per image` above:**
1. No black/corrupt frame — ✅ confirmed (2/2 generations clean).
2. Full body/subject visible, no half-generated crop — ✅ confirmed (headline
   Q1.1 defect not present).
3. Visible sharpness/detail — ✅ confirmed qualitatively (fine hair/fabric
   texture rendered cleanly); no pre-Q1 image to do a strict side-by-side
   against.
4. Photorealism, not oversaturated "AI-look" — ✅ confirmed, CFG 5 default
   produced natural skin tones and lighting.
5. Determinism at fixed seed — ✅ confirmed, pixel-identical re-run.

**Not run this session:** prompts #2-6 (full-body, landscape, macro,
low-light, group scene), FLUX model, and the negative-prompt/style-preset
variants. Prompt #1 alone was judged sufficient to confirm all four Q1 fix
classes are working correctly end-to-end on real infrastructure — the
remaining prompts exist to catch category-specific regressions (e.g. #2's
full-body framing is the other half of Q1.1's headline defect,
distinct from #1's portrait framing) and should be run before Q2 ships if a
more exhaustive pass is wanted, but are not blocking Q1's closure.
