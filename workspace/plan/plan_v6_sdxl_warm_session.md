# Plan v6 — Real SDXL warm-session serve-loop (image generation, not echo)

**Branch:** `imageLab` (merges → dev). Follow-up to Phase W (W.0/W.1/W.2 code-complete).
**Tracked as:** Phase W → **Step W.3**.

## Context

In the Image Lab, starting a **warm session on the SDXL tab returns text** (`ECHO: <prompt>`) instead
of an image. SDXL's warm session is wired to the **W.0 CPU-echo POC** notebook (`session_poc`) — a
deliberate placeholder flagged in W.1 as *"a real SDXL serve-loop is a follow-up."* Only **FLUX**
currently has a real warm serve-loop (load once → generate many).

The user wants what FLUX already does, for SDXL too: **start a session, load the model once, then
generate images repeatedly without re-loading.** The backend `start_session` is already fully
model-agnostic, so this is just: add an SDXL serve-loop notebook + repoint SDXL's registry entry +
update tests. The frontend already renders PNGs vs text by MIME — no frontend change.

Why it matters: a cold SDXL image re-pays `pip install` + 7 GB dataset mount + model load every time;
a warm session pays that once (~1–2 min for SDXL on a single T4), then each image is inference only.

## Changes

### 1. New notebook — `backend/app/kaggle_templates/image_sdxl_session/notebook.ipynb`
Mirror the FLUX serve-loop (`image_flux_session/notebook.ipynb`) — the model-agnostic template:
- **Cell 0** — verbatim from `image_flux_session`: decode `__PAWN_PAYLOAD_B64__`; Supabase REST
  helpers (`get_session`/`patch_session`/`next_job`/`patch_job`/`png_b64`) with
  `apikey: <anon_key>` + `Authorization: Bearer <session_jwt or anon_key>`.
- **Cell 1** — pip install `diffusers transformers accelerate` (match cold SDXL; `requests` preinstalled).
- **Cell 2** — load SDXL **once** then `patch_session(status="ready", heartbeat_at=...)`; on failure
  `patch_session(status="error", error=...)` + `raise`. Load verbatim from the cold SDXL notebook
  (`image_sdxl/notebook.ipynb` cell 2): walk `/kaggle/input` for `model_index.json`, then
  `AutoPipelineForText2Image.from_pretrained(target_dir, torch_dtype=torch.float16, use_safetensors=True, local_files_only=True).to("cuda")`,
  `pipe.set_progress_bar_config(disable=True)`.
- **Cell 3** — serve loop structurally identical to FLUX cell 3 (heartbeat; honor `stopping`/`ended`,
  `expires_at`, `max_images`; pop oldest `queued` job), with SDXL inference:
  `pipe(prompt=job["prompt"], num_inference_steps=4, guidance_scale=0.0, height=512, width=768).images[0]`
  → `patch_job(status="done", image_b64=png_b64(image), mime="image/png", via="kaggle:sdxl-session", done_at=...)`,
  bump `images_done`; on exception `patch_job(status="error", error=str(e), ...)`.
- `metadata.kaggle`: `accelerator nvidiaTeslaT4`, GPU + internet enabled.

### 2. Registry — `backend/app/core/image_models.py` (SDXL entry)
- `session_template = KAGGLE_TEMPLATES_DIR / "image_sdxl_session" / "notebook.ipynb"`
- `session_slug = "pawn-sdxl-session"`
- `session_gpu = True`  *(start_session then mounts `spec.dataset` + requests `spec.accelerator`)*
- Drop the now-unused `KAGGLE_SESSION_POC_TEMPLATE` / `KAGGLE_SESSION_SLUG` imports here (they stay
  defined in `constants.py`; the `session_poc` notebook stays in the repo as the W.0 artifact, just
  unreferenced by any model).

No change in `core/image_session.py` or any route.

### 3. Tests — `backend/tests/test_image_session.py`
- Rewrite `test_start_session_inserts_row_and_pushes_cpu_notebook` → assert SDXL now pushes the GPU
  serve-loop (`enable_gpu True`, `dataset_sources == [sdxl.dataset]`, `accelerator == sdxl.accelerator`,
  `kernel_name == "pawn-sdxl-session"`), parallel to `test_start_session_flux_uses_gpu_and_dataset`.
- Add a session-slug↔title invariant assertion (every model's `session_slug` slugifies back to itself).
- The anon-key security test (uses `sdxl`) still holds.

### Frontend — none
`ImageGenerator` renders `<img>` when `result.mime` starts with `image/` else text; `GenerationsPanel`
lazy-loads thumbnails. SDXL sessions returning `image/png` Just Work.

## Out of scope / notes
- **Quality:** keep cold params (4 steps / guidance 0 / 512×768) for consistency; SDXL quality tuning
  is a pre-existing separate deferred item.
- **Scoped per-session JWT** stays deferred (mandatory before multi-user); notebook already honors an
  injected `session_jwt` if present.
- **Concurrent GPU sessions:** SDXL + FLUX at once = two GPU kernels (Kaggle quota/concurrency limits);
  the timer + image cap are the controls.

## Verification
1. `docker compose exec backend python -m pytest -q` green.
2. `docker compose up -d --build backend`.
3. Image Lab → SDXL → Connect → Warm session → Start → `Warm` in ~1–2 min.
4. Generate → returns an **image** (`via kaggle:sdxl-session`), seconds each; thumbnails in Generations.
5. Kaggle UI shows `pawn-sdxl-session` (GPU T4) running until Stop/timer/cap.
6. Cold Generate (no session) still returns an image; FLUX session unaffected.
