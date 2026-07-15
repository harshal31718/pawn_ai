# Phase P5 — Post-Production Chain: Upscale, Interpolate, Audio, Mux

**Goal:** the polish layer that separates "AI clip" from "finished video" — every generation
can flow through 4K upscale (SeedVR2), frame interpolation to 30/60 fps (RIFE), audio
(MMAudio / native), and ffmpeg finishing — as pipeline stages on the gpu backend (with
hosted-API fallbacks for users without GPU keys).

**Read first:** `01_research_stack.md` §4, P1 DAG columns (`stage`, `depends_on_job_id`,
`pipeline_id`), P3 worker/workflow architecture.

**Branch:** `dev`. Steps P5.1–P5.4.

---

## P5.1 — Stage execution over the DAG

**Files:** `core/video_jobs.py` (stage scheduler), `core/video_exec/*`, tests.

- Scheduler: when a job completes, any `queued` jobs with `depends_on_job_id = it` become
  dispatchable (single background tick loop or dispatch-on-completion callback — pick the
  simpler; document). Stage jobs read their input via the parent's `artifact_ref`.
- Pipeline creation helper: `create_pipeline(user, stages_spec) -> pipeline_id` inserting
  linked rows atomically. Cancellation cascades down the chain.
- UI: gallery card for a pipeline shows a stage progress strip
  (`generate ✓ → upscale ⏳ → interpolate · → audio ·`), collapsible; the card poster
  updates as later stages complete.

**Tests:** DAG dispatch ordering, failure mid-chain (downstream marked skipped/error),
cancellation cascade, atomic creation.

## P5.2 — Upscale + interpolate stages

**Files:** `workers/comfy/workflows/{seedvr2_upscale,rife_interp}.json`, registry stage
rows (stages are registry entries too: `stage_seedvr2`, `stage_rife` with per-stage cost
estimates), api-tier fallback row (`stage_seedvr2_fal` — fal hosts SeedVR2).

- SeedVR2: 720p→4K (or 2× tiers); L40S/A100 suffices (cheaper than H100 — per-stage
  `gpu_type` in registry). RIFE: 16→32/60 fps, cheap GPU.
- Defaults: Pro pipeline = none (hosted models are already 1080p-good); Max pipeline =
  upscale + interpolate on. User toggles per-generation in composer "Finishing" section.

**Tests:** workflow param mapping, estimate math per stage; live gate in P5.4.

## P5.3 — Audio + mux stages

- `stage_mmaudio` (gpu): MMAudio video→synced-audio workflow; prompt-able ("rain, distant
  thunder"). Rows generated on LTX-2/Veo skip it by default (native audio already).
- `stage_mux` (cheap CPU worker or backend-side ffmpeg): final container, loudness
  normalize, optional watermark-free clean export + a small `poster.jpg` refresh.
- Composer "Audio" section: none / native (if model supports) / MMAudio prompt box.

**Tests:** skip-logic (native-audio models), mux param handling.

## P5.4 — Live verification + Max preset

- Define the **"Max" quality preset end-to-end**: draft(seedance-fast) → final(wan14b-hd or
  veo) → seedvr2 4K → rife 60fps → mmaudio → mux. Run it live; record total wall time +
  itemized cost in dev_log (target: <$1.50, <25 min).
- A/B archive: keep the pre/post artifacts of one clip in Drive as the demo receipt.

---

## Risks

| Risk | Mitigation |
|---|---|
| Chain doubles-to-triples cost per clip | stages opt-in, itemized in the pre-submit estimate; Max preset shows full breakdown |
| 4K artifacts through Drive playback | poster + progressive tiers (keep 1080p artifact alongside 4K master) |
| MMAudio quality misses | prompt box + regenerate-audio-only action (stage re-run without re-gen) — cheap by design |
