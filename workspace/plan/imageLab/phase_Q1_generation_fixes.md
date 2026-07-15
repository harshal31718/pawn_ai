# Phase Q1 — Generation Correctness Fixes (the flaw killers)

**Goal:** eliminate the reported defects — half-generated/deformed bodies, black/partial
images, soft output — with five small, additive, individually-verifiable fixes. No new
models, no new features. This phase alone should transform perceived quality.

**Read first:** `01_research_quality.md` §1–3, both SDXL notebooks (cold + session),
`frontend/src/components/AdvancedParams.tsx`, `backend/app/routes/generate.py`
(param models), `image_models.py`.

**Branch:** `dev`. Steps Q1.1–Q1.5 in `build_tracker.md`.

---

## Q1.1 — SDXL-native resolution buckets (headline fix)

**Files:** `frontend/src/components/AdvancedParams.tsx`, `backend/app/routes/generate.py`
(server-side clamp), tests.

- Replace `RATIO_TO_SIZE` with per-model bucket maps (model-aware like `initialAdvanced`):
  SDXL: 1:1→1024×1024, 3:4→896×1152, 4:5→832×1216, 4:3→1152×896, 16:9→1344×768,
  9:16→768×1344. FLUX: same labels, sizes may stay (flexible arch) but round to /16.
- Server-side guard in the params model: snap incoming width/height to the nearest valid
  bucket for SDXL-family rows (protects API callers + old cached frontends). Add
  `resolution_buckets` to the model row so it's data, not code.
- **Default aspect changes to 3:4 portrait 896×1152** (current default was square 512!).

**Tests:** bucket snap unit tests; UI renders new labels. **A/B:** same prompt+seed at old
576×1024 vs new 768×1344 — expect the half-body defect to vanish.

## Q1.2 — fp16 VAE fix (black-image killer)

**Files:** both SDXL notebooks (cold + session), weights-dataset doc, template tests.

- Load `madebyollin/sdxl-vae-fp16-fix` as the pipeline VAE
  (`AutoencoderKL.from_pretrained(..., torch_dtype=float16)` → `pipe.vae = vae`).
  Preferred: add the ~335 MB weights to the SDXL Kaggle dataset (BEAM rule: no runtime
  downloads); acceptable interim: runtime download with a loud `[pawn]` log line.
- FLUX unaffected (different VAE) — no change.

**Tests:** template grep (vae fix present in both SDXL templates, cell-0 untouched).
**A/B:** 20 consecutive warm generations → zero black/corrupt frames.

## Q1.3 — Scheduler + tuned defaults

**Files:** both SDXL notebooks, `AdvancedParams.tsx` (`initialAdvanced` + slider ranges),
`image_models.py` (per-row default fields), tests.

- SDXL notebooks: set `DPMSolverMultistepScheduler.from_config(pipe.scheduler.config,
  use_karras_sigmas=True, algorithm_type="sde-dpmsolver++", euler_at_final=True)` after
  load (research §3 — includes the documented <50-step stability flags).
- Defaults re-centered (data-driven via model rows): SDXL steps 30 (range 20–40 exposed as
  "recommended"), CFG default 5, UI hint "3–5 = more photoreal"; FLUX steps 4, guidance
  locked 0 (already correct).
- Optional row field `scheduler: "dpmpp_2m_sde_karras" | "default"` so future models pick
  their own — data, not code.

**Tests:** template greps; defaults surface per model in UI. **A/B:** fixed prompt+seed,
old vs new scheduler at 30 steps.

## Q1.4 — Seed control + FLUX negative-prompt honesty

**Files:** notebooks (seed already read? verify — add `generator=torch.Generator(...).
manual_seed(seed)` where missing), `routes/generate.py` params (`seed: int | None`),
`AdvancedParams.tsx` (seed field + 🎲 randomize + seed shown on job rows for reproducible
A/Bs), GenerationsPanel (display seed, "reuse seed" action).

- Hide the negative-prompt field when the selected model ignores it (FLUX, CFG 0) instead
  of silently dropping it — honesty rule from F-2's reasoning.

**Tests:** seed round-trips job→notebook→row; determinism test at fixed seed (template-level
grep + one integration assertion on params passthrough).

## Q1.5 — A/B benchmark set + live verification

- Define `imageLab/benchmarks.md`: 6 fixed prompts (portrait, full-body, landscape, object
  macro, low-light, group scene) × fixed seeds. Run pre-fix (dev as-is) and post-Q1 on a
  live warm SDXL session; embed/reference results in dev_log. This set becomes the
  regression baseline for Q2–Q4.
- Live checklist: no black frames in 20 gens; 9:16 full-body prompt renders whole person;
  visible sharpness gain from scheduler.

---

## Risks

| Risk | Mitigation |
|---|---|
| 1024-class gens slower on T4 | warm sessions absorb it; measured + shown via existing elapsed ticker; steps default 30 not 40 |
| VAE weights add dataset step | interim runtime download allowed with loud log; ~335 MB is small |
| Old frontends send old sizes | server-side bucket snap (Q1.1) |
