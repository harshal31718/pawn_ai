# videoLab — Master Plan (Overview)

**Status:** PLANNED (not started)
**Branch:** all work on `dev` (never `main`)
**Plan folder:** `workspace/plan/videoLab/` — this file is the index; phases are separate files.
**Date:** 2026-07-15

---

## 1. What videoLab Is

videoLab = **imageLab's Kaggle integration** + **BEAM's video-generation knowledge**, merged into
one PAWN feature: generate short videos (T2V and I2V) on free Kaggle GPUs from the PAWN UI,
with the same warm-session / cold-job / timer / model-switch experience imageLab already has.

- **imageLab (in this repo, live in prod)** supplies the entire delivery mechanism: Kaggle
  Kernels REST client, notebook templates with payload injection, PostgREST job rendezvous,
  warm serve-loop sessions with heartbeats/timers/extend/stop, dead-session detection,
  cold one-shot jobs, the jobs panel UI, and the per-model panel layout.
- **BEAM (separate repo, REFERENCE ONLY — never write to it)** supplies the video knowledge:
  which engines/models actually run on T4s without OOM (Wan2GP + mmgp Profile 4 + GGUF),
  weight caching via Kaggle datasets, frame-count snapping (8n+1), 9:16 resolution choices,
  scene-by-scene reel assembly ideas, and a long list of resolved setup landmines.

## 2. Source Material (implementing agent MUST read these first)

| What | Where | Why |
|---|---|---|
| imageLab implemented phase doc | `workspace/implemented_phases/phase_05_kaggle_image.md` | Architecture we clone |
| imageLab session issues + fixes | `workspace/plan/plan_imagelab_session_issues.md` | Bugs we must not re-introduce |
| Model registry pattern | `backend/app/core/image_models.py` | videoLab copies this pattern |
| Session lifecycle + job layer | `backend/app/core/image_session.py` | The core to mirror |
| Kaggle client | `backend/app/core/kaggle.py` | Reused as-is (model-agnostic) |
| Cold dispatch | `backend/app/core/generate.py` | Reused pattern |
| Routes | `backend/app/routes/generate.py` | Route pattern to mirror |
| Notebook templates | `backend/app/kaggle_templates/image_*_session/notebook.ipynb` | Serve-loop pattern |
| Frontend Lab UI | `frontend/src/components/ImageLabPage.tsx`, `SessionBar.tsx`, `GenerationsPanel.tsx`, `ImageGenerator.tsx`, `AdvancedParams.tsx` | UI to mirror |
| BEAM plan (reference) | `BEAM repo: docs/plan.md` (v3.2) | Engine/model/quality knowledge |
| BEAM state (reference) | `BEAM repo: docs/state.md` | Resolved setup issues, confirmed APIs |

> BEAM is a read-only reference. If the BEAM folder is not mounted in a future session, the
> relevant knowledge is duplicated into `01_research_models.md` — the plan is self-contained.

## 3. Locked Product Decisions

1. **Two-tier engine strategy.**
   - **Tier 1 (default, Phases V1–V4): Wan2.2 TI2V-5B via Diffusers** — dense 5B, T2V + I2V in
     one checkpoint, 720p (704×1280), fits a single T4 (~8–12 GB with offload), ~9 min per
     5 s clip. Same Diffusers notebook style as imageLab's SDXL/FLUX notebooks — lowest-risk
     path to a working videoLab.
   - **Tier 2 (quality, Phase V5): Wan2GP + mmgp Profile 4 + GGUF** — LTX-2 distilled GGUF
     (fast, BEAM-verified on 1×T4) and Wan2.2 14B I2V/FLF GGUF Q4_K_M (best quality, native
     first/last-frame). Wired through the same registry so it's just more model rows.
   - BEAM's hard lesson: pure Diffusers OOM'd on LTX — but that was LTX 2B early builds; Wan2.2
     5B is designed for consumer GPUs. If V1 hits OOM on T4, fall forward to Tier 2 for ALL
     models (contingency in `phase_V1_foundation_cold_t2v.md` §Risks).
2. **Model switching is data, not code** — `video_models.py` registry mirrors
   `image_models.py`: one row + one notebook template per model. UI renders one panel per model.
3. **Warm/cold duality preserved** — cold one-shot job AND warm serve-loop session per model,
   identical to imageLab (same countdown timers, extend, stop, heartbeats, dead-session probes).
4. **Separate tables** — `video_sessions` + `video_jobs`, mirroring `image_sessions`/`image_jobs`
   schemas (+ video columns). Do NOT add a `modality` column to the live image tables; imageLab
   is in prod and stays untouched. A later consolidation refactor is possible but out of scope.
5. **Result transport** — MP4 base64 in the job row via PostgREST (same rendezvous as images).
   5 s / 720p ≈ 2–8 MB → base64 ≈ 3–11 MB. Prod Nginx `client_max_body_size` is already 20m
   (raised for FLUX images); V1 must verify and bump to 50m in dev + prod configs. Drive upload
   is the Phase V6 upgrade path for longer reels.
6. **Weights come from Kaggle datasets, never runtime downloads** (BEAM Phase 1b rule).
   Each model row names its dataset; notebooks mount it read-only. Multi-GB downloads inside a
   session waste the startup window and risk HF rate limits.
7. **UI = imageLab architecture, Higgsfield-inspired presentation, mobile-first** — same
   structural skeleton (credentials block on top, stacked always-mounted per-model panels,
   SessionBar with warm timer + extend/stop, live elapsed tickers) but presented as a
   gallery-first video product: responsive video-card grid with hover/tap loop previews,
   prominent prompt composer with aspect/duration/motion-preset chips, lightbox player.
   **Mobile responsiveness is a hard requirement** (360 px up) — full spec in
   `phase_V3_ui_video_lab.md`.
8. **BEAM's multi-scene reel pipeline** (planner/prompt-expand/stitch agents) is **Phase V6,
   deferred** — single-clip generation must be rock solid first. V1–V5 keep the door open
   (params carry `start_image` / `end_image` from day one where the model supports it).

## 4. Hard Rules (inherited from PAWN + imageLab, restated)

- All new backend code follows `.claude/rules/backend.md`; frontend follows `frontend.md`;
  secrets/security per `security.md`; test gates per `testing.md`.
- Kaggle + PostgREST calls always via `run_in_threadpool` — never block the event loop.
- Only the PostgREST anon key + URL are injected into notebooks. Never the service key,
  never Kaggle creds, never PAWN secrets. Free Kaggle notebooks are PUBLIC.
- `NvidiaTeslaT4` accelerator = a 2×T4 (2×16 GB) box. Tier-1 video uses one T4; the second
  card stays free (future: judge/T2I — see V6).
- Notebook cell-0 (the PostgREST helper block) must stay byte-identical across all session
  templates (existing test `test_kaggle_session_templates.py` enforces this for image
  templates; extend it for video templates).
- `patch_session` / `patch_job` in notebooks must use the never-raising `_rest_patch` pattern
  (one retry, loud `[pawn]` log lines, 0-row-write detection) — this was a live-debugged fix.
- Tests green (`docker compose exec backend pytest -n auto`) + `npm run build` clean before any
  step is `[x]`. Update `workspace/status/build_tracker.md`, `workspace/current_state.md`,
  `workspace/status/dev_log.md` after every step.
- Use the `build-step` skill for each numbered step (auto-runs code-reviewer, test-runner,
  security-auditor when touching secrets, build-validator).

## 5. Phase Index (implementation order)

| Phase | File | Delivers | Depends on |
|---|---|---|---|
| V0 | `01_research_models.md` | Model/engine reference (no code) — read first | — |
| V1 | `phase_V1_foundation_cold_t2v.md` | `video_models.py`, `video_jobs` table, cold T2V job with Wan2.2 5B, minimal API | — |
| V2 | `phase_V2_warm_sessions.md` | `video_session.py`, warm serve-loop notebook, timers/extend/stop/heartbeats | V1 |
| V3 | `phase_V3_ui_video_lab.md` | VideoLabPage (imageLab-style UI), video player, jobs panel, session bar | V1 (cold), V2 (warm) |
| V4 | `phase_V4_i2v_params.md` | Image-to-video (upload + "Animate" from imageLab generations), advanced params | V1–V3 |
| V5 | `phase_V5_model_switching_quality.md` | Wan2GP/mmgp GGUF engine tier: LTX-2 distilled + Wan2.2 14B FLF; model switch UI proof | V1–V4 |
| V6 | `phase_V6_reels_pipeline.md` | DEFERRED — multi-scene reels, stitching, scene continuity (BEAM's endgame) | V1–V5 |

Each phase file contains numbered steps (V1.1, V1.2, …) sized for one build-step run each,
with per-step files-touched lists, tests, and demo criteria.

> **videoLab 2.0 exists:** `v2/` contains the compute-unconstrained premium plan
> (paid GPUs + hosted SOTA APIs, Higgsfield-level pipeline). Build basic V1–V4 first;
> note that 2.0's P2 (api tier) largely supersedes V5's free-tier quality work — see
> `v2/00_overview_v2.md` §3.8 before starting V5.

## 6. What Success Looks Like

A user with saved Kaggle creds opens Video Lab, starts a warm Wan2.2-5B session, watches the
same warmup phases imageLab shows ("Waiting for Kaggle GPU… → Installing… → Loading model…"),
then submits prompts and gets 5 s 720p vertical clips back in the Generations panel with live
elapsed timers — and can switch to LTX-2-distilled or Wan2.2-14B panels for speed/quality
trade-offs, or animate any image they generated in imageLab.
