# Phase Q4 — Detail & Polish: Hires Fix, Face Detailer, FreeU, Refiner

**Goal:** the finishing layer — fix the remaining realism killers (soft detail, broken
faces at distance) with Diffusers-native, T4-viable techniques, exposed as a single
"Quality boost" toggle rather than a settings wall. All notebook-side; reuses the img2img
plumbing that already exists (IR-1..IR-3).

**Read first:** `01_research_quality.md` §6, Q1.5 benchmark results (what still looks
weak after Q1–Q3 decides emphasis here), both session notebooks' img2img branches.

**Branch:** `dev`. Steps Q4.1–Q4.4. **Each technique lands behind its own param flag and
proves itself on the benchmark set before becoming part of the default boost recipe.**

---

## Q4.1 — Two-pass hires fix

**Files:** SDXL session notebooks, params (`hires_fix: bool`, `hires_scale: 1.5`,
`hires_strength: 0.3`), AdvancedParams row, tests.

- Pipeline: generate at native bucket → lanczos/latent upscale ×1.5 → img2img pass at
  strength 0.25–0.4 with the same prompt (uses the existing `AutoPipelineForImage2Image
  .from_pipe(pipe)` — no extra model in VRAM). Time cost ≈ +60–80% of a base gen —
  acceptable warm; UI shows it in the elapsed ticker; flag stored in params for the
  GenerationsPanel pill.
- Guard: output capped ≤ ~1536×2048 to keep T4 VRAM + transfer sizes sane.

**Tests:** template greps (branch present, cap enforced); params passthrough.
**A/B:** benchmark portraits ±hires — expect visible micro-detail gain.

## Q4.2 — Face detailer (ADetailer-style)

**Files:** SDXL session notebooks (+ small face-detector dependency), params
(`face_detail: bool`), tests.

- Detect faces (mediapipe face detection — pip-light, CPU-fast; avoids YOLO weights
  hosting), for each face ≥ threshold: crop with margin → img2img the crop at 768–1024²
  strength ~0.35 with a face-focused prompt suffix → paste back with feathered mask.
- The single highest-impact fix for full-body/group shots (the "broken faces" complaint).
- Runs after hires fix when both enabled. Skip silently when no face found.

**Tests:** template greps; a params matrix test.
**A/B:** group-scene + full-body benchmarks ±face_detail — the receipt for this phase.

## Q4.3 — FreeU spike (cheap, maybe free win)

- One line (`pipe.enable_freeu(s1,s2,b1,b2)` with SDXL-community values), zero weights.
  Model-dependent results → strict A/B on all 6 benchmarks per model row; adopt per-row
  (`freeu: true` row field) only on clear wins; record verdict here either way.

## Q4.4 — "Quality boost" UX + refiner decision + closeout

- Composer gets ONE "Quality boost" toggle = the proven recipe from Q4.1–Q4.3 (per-model,
  from row fields). Advanced panel still exposes individual flags.
- **Refiner decision recorded here:** SDXL refiner stage is DEFERRED unless benchmarks
  still show base-detail weakness after hires+face+FreeU — fine-tuned checkpoints (Q2)
  typically don't need it, and it costs a second model load on T4.
- Closeout: re-run the full benchmark set (sdxl/juggernaut/realvis × boost on/off);
  archive the grid in Drive; update dev_log + this folder's overview success criteria.

---

## Risks

| Risk | Mitigation |
|---|---|
| VRAM spikes from chained passes | from_pipe (shared weights), output caps, sequential passes; measured on live T4 before defaulting on |
| Warm-loop job time triples with all flags | boost recipe tuned for ≤2.5× base time; flags off by default until proven; elapsed ticker keeps it honest |
| mediapipe dep breaks template pins | pinned install in cell-1's try/except block; template tests |
