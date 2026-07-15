# Phase V1 — Foundation: Registry, Tables, Cold T2V Job (Wan2.2 5B)

**Goal:** the smallest end-to-end proof — a prompt goes in through a new `/video/*` API,
a cold Kaggle kernel runs Wan2.2 TI2V-5B, and an MP4 comes back into a `video_jobs` row.
No UI yet (verify via API + a temporary curl/HTTPie check). No warm sessions yet.

**Read first:** `00_overview.md`, `01_research_models.md`,
`backend/app/core/{image_models,generate,image_session,kaggle}.py`,
`backend/app/routes/generate.py`, `backend/app/kaggle_templates/image_sdxl/notebook.ipynb`,
`workspace/status/build_tracker.md`, `workspace/current_state.md`.

**Branch:** `dev`. Register steps V1.1–V1.5 in `build_tracker.md` before starting.

---

## V1.1 — Video model registry + constants

**Files:** new `backend/app/core/video_models.py`, `backend/app/constants.py`,
`backend/app/exceptions.py` (only if a new typed error is needed — prefer reusing
`UnknownModelError`).

Mirror `image_models.py` exactly (same dataclass shape, same docstring contract):

```python
@dataclass(frozen=True)
class VideoModel:
    id: str                    # "wan5b", later "ltxv", "wan14b", "ltx2"
    label: str
    slug: str                  # "pawn-video-wan5b"
    template: Path             # kaggle_templates/video_wan5b/notebook.ipynb
    dataset: str               # Kaggle weights dataset (V1.2 decides exact ref)
    accelerator: str = "NvidiaTeslaT4"
    output_filename: str = "out.mp4"
    mime: str = "video/mp4"
    run_timeout: int = VIDEO_KAGGLE_RUN_TIMEOUT_SECONDS
    session_template: Optional[Path] = None   # V2 fills this
    session_slug: Optional[str] = None
    session_gpu: bool = True
    engine: str = "diffusers"  # "diffusers" | "wan2gp"  (V5 uses wan2gp)
    # generation defaults (per 01_research_models.md)
    default_width: int = 704
    default_height: int = 1280
    default_frames: int = 81   # ~5s @ 16fps, 8n+1-valid
    default_fps: int = 16
    supports_i2v: bool = True
    supports_flf: bool = False # first/last-frame — wan14b only (V5)
```

Registry starts with only `wan5b`. `DEFAULT_VIDEO_MODEL = "wan5b"`.
Constants (new, in `constants.py` next to the IMAGE_ block):
`VIDEO_KAGGLE_RUN_TIMEOUT_SECONDS = 1800` (cold: install + 12 GB weights load + ~9 min gen),
`VIDEO_JOB_POLL_INTERVAL_SECONDS = 5`, plus a `snap_frames_8n1(frames: int) -> int` helper
(here or in a small `core/video_utils.py`) enforcing the 8n+1 rule with tests.

**Tests:** new `backend/tests/test_video_models.py` — registry lookup, unknown-id raises,
frame snapping (80→81, 81→81, 0/negative → minimum 9), defaults sane.
**Done when:** pytest green.

## V1.2 — Weights dataset decision + cold notebook template

**Files:** new `backend/app/kaggle_templates/video_wan5b/notebook.ipynb`; possibly a
one-off helper notebook committed under `scripts/` (dataset publishing is a manual user
step — document it, don't automate).

1. **Dataset:** search Kaggle for an existing public Wan2.2-TI2V-5B-Diffusers dataset
   (like imageLab found public SDXL/FLUX ones). If none exists, write
   `scripts/kaggle_dataset_wan5b.md` documenting the one-time manual publish flow
   (CPU notebook → `huggingface_hub.snapshot_download('Wan-AI/Wan2.2-TI2V-5B-Diffusers')`
   → publish output as dataset) and use the placeholder dataset ref in the registry, to be
   filled by the user. **The build must not depend on runtime HF downloads** (BEAM rule).
   Fallback for pure smoke-testing while the dataset is pending: a `prompt == "warmup"`
   short-circuit (imageLab convention) that skips model load entirely.
2. **Notebook** mirrors `image_sdxl/notebook.ipynb` structure exactly:
   - `__PAWN_PAYLOAD_B64__` placeholder + identical payload-decode preamble.
   - Env cell first: `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`, HF_HOME →
     `/kaggle/tmp` symlink (BEAM disk lesson), tokenizers off.
   - Install cell: keep Kaggle default torch (never pin), `pip install -U diffusers
     transformers accelerate ftfy imageio imageio-ffmpeg` (+ pins only if live run demands;
     record any pin and why in the notebook comment + dev_log).
   - Load `WanPipeline` / TI2V pipeline from the mounted dataset path, fp16,
     `enable_model_cpu_offload()` on `cuda:0` (one T4; the box has two — leave card 1 idle).
   - Generate: `prompt`, `negative_prompt`, `width/height` (default 704×1280),
     `num_frames` snapped 8n+1, `num_inference_steps`, `guidance_scale`, `seed`.
   - Export MP4 via `imageio-ffmpeg` (H.264, `default_fps`); size guard: if >30 MB re-encode
     CRF 28. Write `out.mp4` to output.
   - `prompt == "warmup"` short-circuit before model load (imageLab convention).

**Tests:** extend `backend/tests/test_kaggle_session_templates.py`-style template checks:
placeholder present, warmup short-circuit present, no secrets, valid JSON ipynb.
**Done when:** template tests green. (Live Kaggle run happens in V1.5.)

## V1.3 — `video_jobs` table + cold job layer

**Files:** new `postgres/migrations/2026-07_video_jobs.sql`, `postgres/schema.sql`,
new `backend/app/core/video_jobs.py`, `backend/app/core/generate.py` (reuse or mirror —
see note), `backend/app/constants.py`.

- `video_jobs` mirrors `image_jobs` columns (id, user_id, model, prompt, params JSONB,
  status, error, created_at, started_at, done_at, session_id nullable) with `video_b64`
  instead of `image_b64` + new `duration_s`, `fps`, `width`, `height` result-metadata
  columns. Same permissive-anon RLS caveat as image tables (documented, pre-multi-user).
- `core/video_jobs.py` implements `create_cold_job` (de-duped per `(user, model)` — same
  active-job guard as images), `run_cold_job` (blocking Kaggle round-trip via the
  **unchanged** `kaggle.run_kernel`, model-agnostic already), `get_job`, `list_jobs` with a
  `_JOB_LIST_COLUMNS` tuple that **excludes `video_b64`** (multi-MB rows must never hit list
  queries — imageLab lesson).
- **Reuse note:** `kaggle.py` needs zero changes (it takes template/slug/dataset/timeouts as
  args). `generate.py`'s `generate_image` is image-named but ~90% generic; recommended path:
  extract the generic round-trip into a private helper it and a new thin
  `generate_video` both call, OR just mirror it in `video_jobs.py` if extraction risks the
  live image path. Keep the diff to image files near-zero; imageLab is in prod.

**Tests:** new `backend/tests/test_video_jobs.py` — create/de-dupe/get/list column
exclusion, run_cold_job happy path + Kaggle failure path (mock the Kaggle client, never
real calls). **Done when:** full backend suite green.

## V1.4 — Routes: `/video/*`

**Files:** new `backend/app/routes/video.py`, `backend/app/main.py` (router registration),
`backend/app/app_initializer.py` if singletons are needed.

Mirror `routes/generate.py`'s cold-path surface only:
- `POST /video/generate` → `create_cold_job` + fire-and-forget bg worker (same `_spawn_bg`
  + per-user-model lock pattern).
- `GET /video/job/{id}` → full row incl. `video_b64`.
- `GET /video/jobs?model=&limit=` → list (no payload column).
- Kaggle credential endpoints are shared with imageLab (`/generate/connect` + key_store) —
  do NOT duplicate; videoLab reads the same stored creds.
- Same exception mapping (typed domain errors → HTTP handlers in `main.py`; no try/except
  in routes for expected failures). GPU-limit message reuse ("Kaggle GPU limit reached…").

**Tests:** new `backend/tests/test_video_routes.py` (one file per route module rule) —
happy paths + unknown model 400 + de-dupe 409/400 behavior matching imageLab semantics.
**Done when:** suite green; `docker compose up` boots clean.

## V1.5 — Live verification (needs user's Kaggle creds — the ONE manual gate)

- Bump Nginx `client_max_body_size` to `50m` in dev + `docker-compose.prod.yml`-side configs
  (and note in `deployment.md`'s gotcha list).
- Live: `POST /video/generate {"prompt": "a red cube slowly rotating on a wooden table",
  "model": "wan5b"}` → poll job → MP4 plays. Record real timings (queue, install, load,
  generate) in `dev_log.md` — these calibrate V2's startup-phase messages and timeouts.
- If **OOM on T4** (contingency): flip `wan5b` row to fp8/quantized variant first; if still
  OOM, mark Tier-1-Diffusers refuted in this file + `01_research_models.md` and pull
  Phase V5's Wan2GP engine forward as the default (plan already structured for this swap —
  registry `engine` field exists from V1.1).

**Done when:** a real clip generated end-to-end; all docs updated (`build_tracker.md`,
`current_state.md`, `dev_log.md`).

---

## Risks

| Risk | Mitigation |
|---|---|
| Wan2.2-5B Diffusers OOM on T4 fp16 | offload enabled from day one; fp8 fallback; Wan2GP contingency (V1.5) |
| No public weights dataset exists | documented manual publish flow; warmup short-circuit keeps CI/testing unblocked |
| MP4 > body limits | 50m Nginx bump + notebook re-encode guard |
| Cold run exceeds timeout | `VIDEO_KAGGLE_RUN_TIMEOUT_SECONDS=1800`, calibrate in V1.5 with real timings |
| Touching prod imageLab code | zero-diff rule on image files; extraction only if provably safe (tests) |
