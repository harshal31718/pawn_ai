# V0 — Model & Engine Research Reference

**Status:** REFERENCE (no code). Compiled 2026-07-15 from web research + BEAM's live-verified
findings. This file makes the plan self-contained even if the BEAM repo isn't mounted.

---

## 1. The Hardware Envelope

Kaggle free tier: `NvidiaTeslaT4` = **2× T4, 16 GB each** (sm_75 — no bf16 tensor-core
advantage, fp16 fine), ~30 GPU-hrs/week, 12 h max session (9 h background-commit cap),
~20 GB working disk + ~57 GB `/kaggle/tmp` ephemeral. Free notebooks are **public** — no
secrets inline, ever.

Anything we run must: fit ≤16 GB VRAM (one card) or shard/offload across cards/CPU, tolerate
fp16, and produce a clip in minutes (not hours).

## 2. Candidate Models (researched 2026-07)

| Model | Size / form | VRAM on T4 | Speed (5 s clip) | Modes | License | Verdict |
|---|---|---|---|---|---|---|
| **Wan2.2 TI2V-5B** | 5B dense, Diffusers-native (`Wan-AI/Wan2.2-TI2V-5B-Diffusers`) | ~8–12 GB w/ offload; fp8 ~8–10 GB | <9 min @ 720p (consumer GPU) | **T2V + I2V unified** | Apache-2.0 | **DEFAULT (Tier 1)** |
| **LTX-Video (LTXV) distilled** | ~2B, Diffusers-native (`Lightricks/LTX-Video`) | ~8 GB | Fastest in class — ~90 s on 4090, minutes on T4 | T2V + I2V | Open (LTXV license, commercial OK w/ terms) | **FAST tier (Tier 1)** |
| **Wan2.2 14B I2V/FLF GGUF Q4_K_M** | MoE 14B, GGUF via Wan2GP+mmgp | streams on 1×T4 (mmgp Profile 4) | ~12–18 min | I2V + native **first/last-frame (FLF)** | Apache-2.0 | **QUALITY tier (Tier 2, V5)** |
| **LTX-2 (2.3) 22B Distilled GGUF Q4_K_M** | 22B GGUF via Wan2GP+mmgp | streams on 1×T4 — **BEAM Phase 0 verified, no OOM** | ~10–15 min incl. upscale | T2V/I2V (+audio in full LTX-2) | LTX license | QUALITY-alt (Tier 2, V5) |
| CogVideoX-5B | 5B Diffusers | ~16 GB (tight) | ~2–3 min on 4090 → slow on T4 | T2V | custom | backlog only |
| HunyuanVideo | 13B | >16 GB w/o heavy quant | slow | T2V | Tencent license | rejected (VRAM + license friction) |

### Why this beats BEAM's original stack (user asked: "integrate better if found")

BEAM locked onto Wan2GP + GGUF for **everything** because pure-Diffusers LTX 2B OOM'd in
early 2025 builds. Two things changed:

1. **Wan2.2 TI2V-5B** (released after BEAM's plan) is a dense 5B **designed for 8 GB consumer
   GPUs**, Diffusers-native, and does T2V **and** I2V in one checkpoint at 704×1280. This
   removes Wan2GP as a hard dependency for the default path — a plain Diffusers notebook
   (imageLab's exact notebook style) suffices. Simpler = fewer moving parts = warm-session
   loop stays byte-compatible with imageLab's proven template.
2. **LTXV distilled (~2B)** matured into the fastest low-VRAM video model available — few-step
   distilled inference, runs on 8 GB. As a "fast draft" model it beats BEAM's LTX-2 22B GGUF
   path on startup time (no Wan2GP clone/install, no GGUF loader) and per-clip latency.

Wan2GP + mmgp is still the right call for the **quality tier** (14B/22B class on a 16 GB
card is only possible via mmgp streaming + GGUF) — that's Phase V5, and BEAM's Phase-0-verified
setup steps are transplanted there.

## 3. Locked Model Lineup for videoLab

| id | Label | Engine | Notebook style | Phase |
|---|---|---|---|---|
| `wan5b` | Wan2.2 5B (T2V+I2V) | Diffusers fp16 + offload, 1×T4 | imageLab-style session/cold notebook | V1 |
| `ltxv` | LTX-Video Distilled (fast) | Diffusers, 1×T4 | same | V4/V5 (second Tier-1 model — proves model switching) |
| `wan14b` | Wan2.2 14B FLF (quality) | Wan2GP + mmgp Profile 4 + GGUF Q4_K_M | Wan2GP headless `shared.api` notebook | V5 |
| `ltx2` | LTX-2 22B Distilled (quality-alt) | Wan2GP + mmgp + GGUF | same as wan14b | V5 (optional, same template family) |

## 4. BEAM Knowledge Transplant (verified facts — do not rediscover)

### Wan2GP headless API (BEAM-confirmed from source, Phase 0 ran it live)
```python
from shared.api import init
session = init(root=Path('/kaggle/working/Wan2GP'),
               output_dir=Path('/kaggle/working/outputs'),
               cli_args=['--profile','4','--attention','sdpa','--gpu','cuda:0'])
job = session.submit_task(settings_dict)   # settings = WanGP "Export Settings" shape
res = job.result()                          # res.generated_files -> mp4 path(s)
```
- `--profile 4` = mmgp LowRAM_LowVRAM streaming — **the OOM fix**. Model stays warm across
  `submit_task` calls → maps perfectly onto our warm serve-loop.
- BEAM Phase 0 measured: LTX-2 22B Q4 on 1×T4 → ~53 s/step × 8 steps + VAE decode + spatial
  upscale ≈ 10–15 min/clip; GPU 100% util at only 2.2 GB VRAM resident (mmgp streaming).

### Resolved setup landmines (cold-start reference — bake into notebook templates)
- numpy 2.x / scipy conflict → pin `numpy==1.26.4 scipy==1.13.1` in the install cell.
- Wan2GP needs a **full clone** (not `--depth 1`) — `shared.utils` missing otherwise; then
  `sys.path` insert + `os.chdir(WAN_ROOT)`.
- Do NOT set `HF_HUB_ENABLE_HF_TRANSFER` without installing `hf_transfer`.
- Disk: symlink `HF_HOME` and `Wan2GP/ckpts` → `/kaggle/tmp` (57 GB) — `/kaggle/working` is
  only ~20 GB and fills up.
- **T4 = keep Kaggle's default torch.** Never pin `torch==2.3.1` (that was a P100 fix).
- Frame counts must snap to **8n+1** (Wan/LTX families). Helper: `f = 8*round((f-1)/8)+1`.
- Env hygiene cell first: `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`, tokenizers
  parallelism off.

### Weight strategy (BEAM Phase 1b rule — applies to every videoLab model)
**Never auto-download weights at session start.** Per model: one-time manual step — download
weights in a CPU notebook → publish as a private Kaggle dataset → the model row in
`video_models.py` names the dataset → notebook mounts it read-only and symlinks into the
path the engine expects. imageLab already works this way (`steubk/stable-diffusion-xl-base-1-0`
etc.); videoLab model rows do the same. Wan2.2-5B Diffusers weights ≈ 12 GB → dataset.
Existing public datasets should be searched first (like imageLab found public SDXL/FLUX
datasets); publish private ones only if nothing public exists.

### Prompting/quality knowledge worth carrying (BEAM clip analysis)
- One clip = one action. Asking a single clip for a transformation ("morphsuit → outfit")
  produces chaotic motion. Keep prompts single-scene; multi-scene = V6's stitch pipeline.
- 9:16 vertical 704×1280 is the native sweet spot for Wan2.2; don't internally upscale.
- Quality levers in order: steps (8→12), quant tier (Q4→Q6/Q8), refined prompt. Slow is
  accepted; mmgp adds capacity, not speed.

## 5. Transport Sizing (video vs image)

- 5 s @ 720p H.264 ≈ 2–8 MB → base64 ≈ 3–11 MB per job row. PostgREST/Nginx path already
  proven to 20 MB (prod `client_max_body_size 20m`, raised for FLUX). V1 bumps to **50m**
  in dev + prod Nginx configs and adds a notebook-side size guard (re-encode at lower CRF if
  >30 MB).
- Job rows with multi-MB base64 must NEVER be selected in list queries — imageLab already
  learned this: `_JOB_LIST_COLUMNS` excludes the payload column. videoLab must do the same
  (`video_b64` fetched only by single-job GET).

## 6. Sources

- Wan2.2 TI2V-5B: https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B and
  https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B-Diffusers (720p ≤9 min consumer GPU, 8 GB+)
- VRAM guide: https://willitrunai.com/blog/wan-2-2-vram-requirements (5B: 8–12 GB; fp8 8–10 GB)
- Wan2GP engine: https://github.com/deepbeepmeep/Wan2GP (Wan 2.1/2.2, LTX-2, LTXV, Hunyuan,
  Flux; 6 GB VRAM floor; headless queue processing)
- LTX-2 requirements: https://docs.ltx.io/open-source-model/getting-started/system-requirements
  and https://wavespeed.ai/blog/posts/blog-ltx-2-vram-requirements/ (12 GB practical baseline
  for small workflows; distilled = 8 steps, cfg 1)
- LTXV speed on low VRAM: https://www.hyperstack.cloud/blog/case-study/best-open-source-video-generation-models
  and https://localaimaster.com/blog/local-ai-video-generation (LTX-Video on 8 GB; ~7 min on
  a 3060-12GB class card)
- 2026 landscape roundups: https://ltx.io/blog/best-open-source-video-generation-models ,
  https://www.pixazo.ai/blog/best-open-source-ai-video-generation-models
- BEAM live-verified engine facts: BEAM repo `docs/state.md` (Phase 0 complete section) —
  reference only.
