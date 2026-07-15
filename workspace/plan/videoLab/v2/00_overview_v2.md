# videoLab 2.0 — Master Plan (Overview)

**Status:** PLANNED (build AFTER basic videoLab V1–V4 is live; V5 free-tier quality work may
be deprioritized in favor of 2.0 — decision point noted below)
**Branch:** `dev`
**Plan folder:** `workspace/plan/videoLab/v2/` — basic videoLab plan lives one level up.
**Date:** 2026-07-15

---

## 1. What 2.0 Is

Basic videoLab = free Kaggle T4s, compute-resistant, minutes-per-clip, open 5B-class models.
**videoLab 2.0 forgets compute resistance.** Target: **Higgsfield-level output and workflow**
— SOTA model quality, cinematic camera control, character consistency, 4K polished output,
seconds-to-low-minutes turnaround — using paid compute and every available *jugad*.

Higgsfield's actual anatomy (researched — see `01_research_stack.md`): it is an
**aggregator + control layer + post chain**, not a model. It routes to hosted SOTA models
(Seedance 2.0, Kling 3.0, Veo 3.x, Sora 2, Wan 2.6, Hailuo), layers 100+ camera/motion
presets on top, adds character consistency (Soul ID), lipsync studio, and Topaz-powered
upscaling. **That architecture is exactly what PAWN is already good at:** BYOK provider
aggregation + registry-as-data + failover chains. 2.0 = apply PAWN's chat-provider playbook
to video.

## 2. The Three Execution Tiers (core architectural idea)

| Tier | Backend | Delivers | Cost model |
|---|---|---|---|
| **free** | Kaggle (basic videoLab, unchanged) | open 5B/GGUF models, minutes | ₹0 |
| **api** | Hosted model APIs — fal.ai (primary aggregator), Replicate (fallback), direct vendor APIs where cheaper | Kling/Veo/Seedance/Wan-2.6/Hailuo-class SOTA, **the Higgsfield jugad** | BYOK, ~$0.03–$0.40/s of video |
| **gpu** | Rented serverless GPUs — RunPod serverless (primary, cheapest ~$1.9–3.5/hr eff.), Modal (fallback, fastest snapshots) | full-precision open SOTA self-hosted (Wan 2.2 A14B bf16, HunyuanVideo 1.5, LTX-2 full w/ native audio), LoRA training, post-production chain | per-second GPU billing |

Every job row carries `backend: kaggle|api|gpu`. The registry decides which backends a model
row supports. UI exposes tier as a simple Quality selector (Draft = free/cheap · Pro = api ·
Max = gpu) — users never think about infrastructure.

## 3. Locked Product Decisions

1. **Additive, not replacement.** Basic videoLab tables/routes/UI stay; 2.0 extends the same
   `video_jobs` pipeline with `backend`, `stage`, and `cost` columns + new executor modules.
   One gallery shows all jobs regardless of backend.
2. **BYOK everywhere.** fal/Replicate/RunPod/Modal keys stored via the existing `key_store`
   (new provider ids), same encryption, same Settings UI section pattern. PAWN never fronts
   compute costs; the user's keys, the user's spend.
3. **Artifacts leave base64.** 2.0 outputs (4K, 10–20 s, audio) blow past PostgREST comfort.
   New artifact store: results land in **Drive** (`PAWN/videolab/` folder) via the existing
   Drive storage layer; job rows carry `artifact_ref` + thumbnail/poster b64 only. (Kaggle
   tier keeps base64 for ≤720p to avoid touching the working path.)
4. **Pipeline = staged DAG, not one call.** A 2.0 "generation" is a chain:
   `enhance-prompt → generate (draft) → [select/judge] → generate (final) → upscale →
   interpolate → audio → mux`. Each stage is a `video_jobs` row linked by `pipeline_id` +
   `depends_on_job_id`; stages can run on different backends (draft on cheap, final on best).
5. **Presets are data.** Camera moves, motion styles, VFX looks = rows in
   `data/registry/video_presets.json` (prompt fragments + per-model param/LoRA mappings),
   NOT frontend constants. Higgsfield's moat is its preset library; ours is registry-driven
   and grows without code changes.
6. **Cost governance is first-class.** Every job stores estimated + actual cost; per-user
   monthly budget with hard stop; estimator shown in the composer BEFORE submit. No silent
   spend, ever.
7. **Judge/auto-quality returns** (BEAM Phase 7's deferred idea, now affordable): VLM judge
   scores drafts, best-of-N on cheap tiers before spending on Max renders.
8. **Decision point:** basic videoLab V5 (Wan2GP GGUF quality tier on Kaggle) becomes largely
   redundant once P2 (api tier) lands — same-or-better quality for cents. Keep V5 in the
   backlog as the ₹0 quality path; do not build it before P2 unless GPU budget is zero.

## 4. Phase Index

| Phase | File | Delivers | Depends on |
|---|---|---|---|
| P0 | `01_research_stack.md` | Research reference: Higgsfield anatomy, APIs, GPU pricing, post stack | — |
| P1 | `phase_P1_execution_backends.md` | Backend abstraction, Drive artifact store, cost ledger + budgets, schema v2 | basic V1–V3 live |
| P2 | `phase_P2_api_tier.md` | fal/Replicate executors, SOTA model rows, instant Higgsfield-grade output | P1 |
| P3 | `phase_P3_rented_gpu_workers.md` | RunPod/Modal serverless ComfyUI workers, warm pools, full-precision open models | P1 |
| P4 | `phase_P4_cinematic_control.md` | Preset library (camera/motion/VFX), start-end frame, VACE control, character refs | P2 (P3 enriches) |
| P5 | `phase_P5_post_production.md` | Upscale (SeedVR2/Topaz-API), RIFE interpolation, audio (MMAudio/native), mux | P3 |
| P6 | `phase_P6_orchestration_quality.md` | Prompt enhancer, draft→final pipelines, best-of-N + VLM judge, Reels 2.0 | P2+P5 |
| P7 | `phase_P7_characters_lipsync.md` | Character library (Soul-ID-like), LoRA training jobs, lipsync studio | P3+P4 |

Recommended build order: **P1 → P2 → P4 → P6(core) → P3 → P5 → P7**, because P2+P4 alone
already deliver visible Higgsfield-level results (hosted SOTA + presets) in days, while P3/P5
build the self-hosted depth.

## 5. Hard Rules (inherited + new)

- All PAWN rules apply (backend/frontend/security/testing rules files; build-step skill;
  docs updated per step; tests green before `[x]`).
- All LLM calls (prompt enhancer, judge prompts, planners) via `normalize.py`. No exceptions.
- New provider keys via `key_store` only; never logged; security-auditor mandatory on every
  step touching executors (they hold spend authority).
- **Spend safety:** executor modules enforce budget BEFORE dispatch; any code path that can
  incur cost must be covered by a test proving budget-stop works.
- External API calls in executors: `run_in_threadpool` / async httpx, typed domain errors,
  failover chains (fal → replicate → vendor) mirroring `llm_core`'s pattern.
- UI stays mobile-first (V3 rules apply to every new surface).

## 6. What Success Looks Like

User types a prompt, taps "Crash zoom" + "Handheld" presets, picks Pro quality, sees
"≈ $0.35 · ~60 s", hits Generate — Kling/Seedance-class 1080p clip lands in the gallery in
about a minute. Taps "Max": draft goes to a cheap model, judge picks the best of 3 seeds,
final renders on Wan 2.2 A14B on an H100, auto-upscales to 4K with SeedVR2, RIFE to 60 fps,
MMAudio soundtrack, lands in Drive — a clip indistinguishable from Higgsfield's output,
inside PAWN, on the user's own keys.
