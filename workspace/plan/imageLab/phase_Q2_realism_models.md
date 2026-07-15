# Phase Q2 — Realism Models: Photoreal Checkpoints as Registry Rows

**Goal:** the realism jump. Base SDXL 1.0 is a 2023-class generalist; Juggernaut XL and
RealVisXL are same-architecture photoreal fine-tunes — identical pipeline, identical VRAM,
just better weights. The registry design means each is one row + one dataset + (reused)
notebook template.

**Read first:** `01_research_quality.md` §4, `image_models.py` docstring ("To add a model:
drop a notebook + add one row"), Q1 results (buckets/scheduler/VAE fixes apply to these
rows automatically).

**Branch:** `dev`. Steps Q2.1–Q2.3.

---

## Q2.1 — Template generalization (one template, many SDXL-family models)

**Files:** `backend/app/kaggle_templates/image_sdxl*/notebook.ipynb`, `image_models.py`,
template tests.

- Current SDXL notebooks hardcode the dataset path/model dir. Generalize: the injected
  payload already carries per-job data — add `model_dir` (mounted dataset subpath) to the
  session payload from the model row, so ONE `image_sdxl_session` template serves every
  SDXL-family checkpoint. Zero logic forks; single-file loads (`from_single_file`) 
  supported for Civitai-style `.safetensors` checkpoints.
- Registry row gains: `weights_format: "diffusers" | "single_file"`, `model_dir`,
  and Q1.3's per-row defaults (steps/cfg/buckets/scheduler).

**Tests:** template tests still enforce cell-0 byte-identity; payload carries model_dir;
sdxl row unchanged behavior (regression).

## Q2.2 — Juggernaut XL + RealVisXL rows

**Files:** `image_models.py` (+2 rows), `scripts/kaggle_dataset_photoreal.md` (weights
publish doc), frontend (panels appear automatically — verify only).

| id | Weights | Defaults (from research) |
|---|---|---|
| `juggernaut` | Juggernaut XL v10-class | 832×1216 default bucket, DPM++ 2M SDE Karras, steps 35, CFG 4 |
| `realvis` | RealVisXL V5.0 | 896×1152 default, DPM++ 3M SDE Karras (add scheduler option), steps 30, CFG 6 |

- Weights via per-user private Kaggle datasets (publish doc; verify each model's license
  permits private redistribution for personal use — note in the row comment).
- Both get warm-session support for free (same session template family).
- Kaggle 2-GPU cap note: more model rows ≠ more concurrent sessions; UI already handles it.

**Tests:** registry rows; template tests across all SDXL-family session slugs.
**A/B (the receipt):** Q1.5 benchmark set on sdxl vs juggernaut vs realvis — expect the
"doesn't look real" complaint to close here.

## Q2.3 — FLUX realism guidance (+ optional dev row, decision)

- FLUX-schnell stays (fast tier); its realism lever is prompting → handled in Q3 (prompt
  enhancer emits FLUX-style natural-language + realism descriptors; UI hides negatives).
- **Decision recorded here:** FLUX.1-dev row is OPTIONAL and default-off — non-commercial
  license + 20–30 steps (~3–5× schnell time on T4). Add only if Q2.2's SDXL fine-tunes
  don't satisfy; if added, it's one row + one dataset via the generalized template pattern
  (FLUX family needs its own template generalization mirroring Q2.1 — small).

---

## Risks

| Risk | Mitigation |
|---|---|
| Checkpoint licenses vary (Civitai) | verify per model before dataset publish; private per-user datasets only; note in row comment |
| Fine-tune breaks img2img/refine path | IR-flow is pipeline-generic (`from_pipe`); covered by A/B + one refine smoke test per new row |
| Dataset size (6–7 GB each) | one-time publish per model; BEAM rule keeps sessions fast |
