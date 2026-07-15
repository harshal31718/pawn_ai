# Phase P3 — Rented GPU Workers: Serverless ComfyUI (Self-Hosted SOTA)

**Goal:** the `gpu` backend — RunPod serverless (primary) / Modal (fallback) running a
headless **ComfyUI worker image**, giving videoLab what hosted APIs can't sell: full-precision
open SOTA (Wan 2.2 A14B bf16/fp8, HunyuanVideo 1.5, LTX-2 full with native audio), LoRA
stacking, control nets (VACE), and the P5 post-production chain — billed per second, scale
to zero.

**Read first:** `01_research_stack.md` §3, RunPod serverless docs + Modal docs at build time,
ComfyUI API-mode docs, P1 executor interface. This phase is the reincarnation of basic
videoLab's warm-session concept — same UX (warm pool ≈ warm session, timers, stop), new
substrate.

**Branch:** `dev`. Steps P3.1–P3.5.

---

## P3.1 — Worker image

**Files:** new `workers/comfy/Dockerfile` + `workers/comfy/handler.py` (RunPod handler /
Modal app in one shared module + thin per-provider entrypoints) + `workers/comfy/workflows/`
(ComfyUI workflow JSONs, versioned in-repo).

- Base: CUDA + ComfyUI + pinned node set (Wan nodes, VideoHelperSuite, VACE, SeedVR2, RIFE —
  pin commit hashes; record in image tag). Models NOT baked into the image (huge) — pulled
  from a network volume (RunPod volume / Modal volume) provisioned once per user-region
  (P3.2 bootstrap job) — the 2.0 version of the Kaggle-dataset weights rule.
- `handler.py` contract: input = `{workflow_id, params, artifacts_in (signed refs)}` →
  loads workflow JSON, patches params, runs ComfyUI headless, returns artifact bytes/refs +
  timings + peak VRAM (for cost/telemetry).
- Workflows v1: `wan22_a14b_t2v`, `wan22_a14b_i2v`, `ltx2_t2v_audio`, `hunyuan15_t2v` —
  each 704×1280-default + 8n+1 snapping param mapping.

**Tests:** handler unit tests (workflow patching, param validation) runnable without GPU;
image builds in CI-less fashion documented in `workers/README.md`.

## P3.2 — `gpu_exec` executor + volume bootstrap

**Files:** new `core/video_exec/gpu_exec.py`, `core/video_providers/{runpod,modal}.py`,
registry rows (`wan14b-hd`, `hunyuan15`, `ltx2-audio` with `backend: gpu`, per-row
`gpu_type` (H100/A100/L40S) + `est_sec_per_video_sec` for estimates), tests.

- RunPod client: create/reuse serverless endpoint (per user, from their key), submit job,
  poll, fetch artifact. Modal client mirrors. Endpoint config: min 0 / max 1 workers,
  FlashBoot on, idle timeout from constants.
- **Volume bootstrap job** (`stage='bootstrap'`): first gpu job per user triggers a
  CPU-priced volume-hydration run (HF downloads onto the volume, ~15–30 min, one-time) with
  clear UI messaging — the cold-start jugad that makes every later start fast.
- Estimates: `gpu_hourly_rate × est_runtime` from registry; actuals from provider usage API.

**Tests:** mocked provider matrix, bootstrap-once logic, budget stop, estimate math.
Security-auditor mandatory.

## P3.3 — Warm pool = 2.0 warm sessions

**Files:** `core/video_session.py` (extend, don't fork: `backend` column on
`video_sessions`), `gpu_exec.py`, SessionBar reuse in Studio panel.

- "Start warm session (GPU)" sets endpoint min-workers=1 → worker pre-loads default model →
  status heartbeats via a tiny keepalive job → same SessionBar UX: countdown (idle-timeout
  based, extend = reset), stop = min-workers 0. Per-minute cost shown live on the bar
  (`$0.03/min` style) — a warm H100 is real money; the UI must make that visceral.
- Session-tuned constants: `GPU_SESSION_IDLE_TIMEOUT_MINUTES = 10`,
  `GPU_SESSION_MAX_DURATION_MINUTES = 60`, budget check on start AND on each extend.

**Tests:** lifecycle with mocked provider; cost accrual on warm time; auto-stop at budget.

## P3.4 — LoRA + control readiness (foundations for P4/P7)

- Workflow JSONs accept optional `loras: [{ref, strength}]` (volume paths) and `control`
  blocks (VACE inputs: reference image/pose video refs) — plumbed through params now so
  P4/P7 are registry+UI work, not executor work.
- `train_lora` stage handler skeleton (dataset in → LoRA out to volume) — implementation
  lands in P7.

## P3.5 — Live verification

- Real RunPod key: bootstrap volume → cold Wan 2.2 A14B clip (record cold + warm timings +
  true cost) → warm session: 3 clips, idle auto-stop verified against RunPod dashboard →
  Modal fallback smoke test. Compare A14B-bf16 output vs basic-videoLab wan5b side by side
  in dev_log (the quality receipt for this whole phase).

---

## Risks

| Risk | Mitigation |
|---|---|
| Runaway warm workers = runaway spend | idle timeout + max duration + budget hard stop + live per-min cost UI; auto-stop is provider-side (endpoint config), not just app-side |
| ComfyUI node breakage | commit-pinned nodes, image tags, workflows versioned in-repo |
| Per-user endpoint sprawl | one endpoint per user reused across models (volume holds all weights); document RunPod account limits |
| Modal/RunPod API drift | thin clients + build-time doc re-verify (same rule as P2) |
