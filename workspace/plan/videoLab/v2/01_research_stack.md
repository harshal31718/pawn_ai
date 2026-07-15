# P0 — 2.0 Research Reference: Higgsfield Anatomy, APIs, Compute, Post Stack

**Status:** REFERENCE (no code). Compiled 2026-07-15. Prices/models move fast — re-verify
with a fresh web search at the start of each phase and update this file.

---

## 1. Higgsfield, Deconstructed (what we're matching)

| Higgsfield feature | What it actually is | Our equivalent (phase) |
|---|---|---|
| Model lineup (Seedance 2.0, Kling 3.0, Veo 3.x, Sora 2, Wan 2.6, Hailuo 02) | hosted-API aggregation, per-model routing | P2 api tier |
| Cinema Studio / DoP: 100+ camera presets (dolly, crane, FPV, crash zoom, bullet time) | preset library = prompt fragments + per-model motion params applied across ALL models | P4 preset registry |
| Soul / Soul ID (photoreal images + character consistency) | dedicated image model + identity embedding/LoRA reuse across generations | P7 characters |
| Lipsync Studio (10 models: InfiniteTalk, Kling Avatar, Veo 3, lipsync-2…) | multi-model lipsync aggregation over the same API providers | P7 lipsync |
| Topaz-powered upscale | licensed upscaler API bolted on post-gen | P5 (SeedVR2 self-hosted primary, Topaz API optional row) |
| Draft/quality tiers, credit system | cost-tiered routing + ledger | P1 cost ledger, P6 draft→final |

Takeaway: Higgsfield ships **zero foundation models of its own** for video — the product is
routing + presets + consistency + post + UX. All four layers are buildable on PAWN.

## 2. Hosted Video APIs (the P2 menu; BYOK)

| Model (2026) | Via | Price ballpark | Notes |
|---|---|---|---|
| Seedance (Fast/Pro) | fal / ModelArk direct | ~$0.03–0.05/s | best price/quality draft tier |
| Kling 2.x/3.0 | fal / Replicate | ~$0.07/s | strong motion, native camera params |
| Wan 2.5/2.6 | fal | ~$0.05/s (flat $0.20–0.40/gen elsewhere) | open-family, cheap |
| Veo 3.1 (+Lite) | fal / Gemini API | Lite $0.05/s @720p; full ~$0.40/s | native audio, top realism |
| Sora 2 | API (availability varies) | ~$0.10/s | check access terms at build time |
| Hailuo 02 (MiniMax) | fal / Replicate | mid | good human motion |
| SeedVR2 upscale | fal hosted | per-run | same model we self-host in P5 |

- fal.ai: pure pay-as-you-go, no minimum, output-based billing (per second of video) —
  primary aggregator. Replicate: per-GPU-second billing — fallback + long-tail models.
- Failover chain per model row (fal → replicate → vendor-direct) mirroring `llm_core`.

## 3. Rented GPU Compute (the P3 substrate)

| Provider | Price (2026) | Cold start | Verdict |
|---|---|---|---|
| **RunPod serverless** | H100 ~$1.91/hr eff. (@$0.00053/s), A100-80G ~$3.49/hr on-demand tiers; per-second billing | 20–60 s (sub-200 ms FlashBoot for warm pool) | **PRIMARY** — cheapest, warm pools |
| Modal | H100 ~$10/hr, A100 ~$5.59/hr | 2–30 s, best snapshot tech | fallback / dev ergonomics |
| Vast.ai / spot markets | cheapest raw $/hr | manual, flaky | jugad tier for LoRA training batches only |

- Worker image: **ComfyUI headless** (API mode) — the ecosystem standard; every model/control/
  upscale node we need already exists as ComfyUI nodes (Wan, Hunyuan, LTX-2, VACE, SeedVR2,
  RIFE). One image, many workflows-as-JSON. Alternative kept open: plain diffusers workers
  for simple cases.
- Self-host menu at full precision on H100/A100: Wan 2.2 A14B (bf16/fp8), HunyuanVideo 1.5,
  LTX-2 full (native synchronized audio, 4K-capable distilled workflows), plus LoRA stacking —
  things hosted APIs don't allow.
- Jugad notes: warm-pool 1 worker during active session, scale-to-zero after idle;
  drafts on cheap cards (L40S/4090 rows), finals on H100; spot/community tiers for training.

## 4. Post-Production Stack (P5)

| Stage | Primary (self-hosted, ComfyUI nodes) | Alternative |
|---|---|---|
| Upscale to 4K | **SeedVR2** (2026 standard, studio-grade) / FlashVSR+ | Topaz API (what Higgsfield licenses); fal-hosted SeedVR2 |
| Frame interpolation → 30/60 fps | **RIFE** | FILM |
| Detail/faces | GAN pass (Real-ESRGAN class) where needed | — |
| Audio | **MMAudio** (video→synced audio) or LTX-2 native audio when generating on it | Veo native audio (api tier) |
| Color/stitch/mux | ffmpeg (concat on handoff frames + color normalize — BEAM spec) | — |

## 5. Control & Consistency (P4/P7)

- **Camera control:** hosted models accept camera/motion params or respond strongly to
  preset prompt grammar (Higgsfield's own WAN camera-control guide confirms prompt-drivable);
  self-hosted adds camera-control LoRAs for Wan + **VACE** (pose/depth/flow/reference
  conditioning, Apache-2.0) for real control.
- **Character consistency:** api tier → models' native reference/character features
  (Kling/Seedance reference images, Veo ingredients); gpu tier → identity LoRA training
  (per-character, ~minutes on H100) + reference-conditioned generation (VACE/Phantom-class).
  Character = stored asset: name + reference images + trained LoRA ref + usage notes.
- **Lipsync:** aggregate hosted lipsync models (fal exposes several) — same executor as P2.

## 6. Cost Reality Check (why 2.0 is affordable)

- Pro clip (5 s @ Kling-class): ~$0.35. Draft (Seedance Fast): ~$0.15. 
- Max pipeline (draft ×3 + judge + 5 s H100 final + SeedVR2 + RIFE ≈ 10–15 min H100): ~$0.5–1.0.
- A heavy creative session (30 pro clips + 5 max) ≈ $15–20. Monthly hobbyist budget $25–50
  covers Higgsfield-Pro-plan-level usage — on our own terms, no credit expiry.

## 7. Sources

- Higgsfield anatomy: https://higgsfield.ai/camera-controls · https://higgsfield.ai/ai-video ·
  https://higgsfield.ai/lipsync-studio · https://geo.higgsfield.ai/higgsfield-ai-features-full-guide-2026 ·
  https://kolbo.ai/blog/higgsfield-suite-100-camera-presets ·
  https://higgsfield.ai/blog/turn-your-video-into-cinema-using-wan-camera-control
- API pricing: https://fal.ai/pricing · https://fal.ai/docs/documentation/model-apis/pricing ·
  https://fluxnote.io/blog/ai-video-generation-pricing-guide-2026 ·
  https://www.teamday.ai/blog/ai-image-video-api-providers-comparison-2026
- GPU pricing: https://www.runpod.io/pricing · https://docs.runpod.io/serverless/pricing ·
  https://www.spheron.network/blog/runpod-h100-pricing-2026/ ·
  https://www.buildmvpfast.com/blog/scale-to-zero-serverless-gpu-modal-runpod-ai-hosting-2026
- Post stack: https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler ·
  https://huggingface.co/blog/MonsterMMORPG/seedvr2-and-flashvsr-studio-level-image-and-video ·
  https://www.aiarty.com/ai-video-enhancer/open-source-video-upscaler-enhancer.htm
