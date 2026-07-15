# Phase V4 — Image-to-Video, Cross-Lab "Animate", Second Fast Model

**Goal:** the feature that makes videoLab feel magic — animate any image: an upload, or any
imageLab generation ("Animate" button on image cards), or a previous video's last frame
(continuation seed for V6 reels). Plus land the second Tier-1 model (`ltxv`) to prove the
model-switching registry with a genuinely different speed profile.

**Read first:** imageLab's img2img implementation (Plan 2 / IR-1..IR-3 in
`workspace/implemented_phases/phase_05_kaggle_image.md`) — V4 is its video twin:
`_resolve_init_image`, `init_image_b64`/`init_job_id` request fields, params JSONB merge,
client-side resize, the Refine/`useImperativeHandle` pattern.

**Branch:** `dev`. Steps V4.1–V4.4 in `build_tracker.md`.

---

## V4.1 — Backend I2V routing

**Files:** `backend/app/routes/video.py`, `backend/app/core/video_jobs.py`,
`backend/app/core/video_session.py`, tests.

- `GenerateRequest`/`SessionJobRequest` (video) gain `init_image_b64: str | None`,
  `init_image_job_id: str | None` (an **image_jobs** id — cross-lab!), and
  `init_video_job_id: str | None` (extract last frame of a done video job, backend-side via
  ffmpeg-less approach: store `last_frame_b64` written by the notebook alongside `video_b64`
  — add that column/notebook write in this step; cheaper than server-side video decoding).
- `_resolve_init_image` mirror: resolves whichever source is set (validate exactly one),
  enforces `user_id` ownership on both referenced tables, merges resolved b64 into `params`
  JSONB. Wan2.2 TI2V consumes it as the conditioning image; `strength`-like knobs don't apply
  (I2V here = first-frame conditioning, not img2img denoise — document in code comment).
- Notebook (`video_wan5b` + session variant): branch on `params.init_image_b64` → I2V call
  path of the same pipeline (TI2V is unified — no extra model load); resize/letterbox the
  init image to the requested WxH notebook-side; also write `last_frame_b64` on every done
  job (feeds continuation + V6 handoff).

**Tests:** resolve matrix (each source, ownership guard, exactly-one validation), template
greps for I2V branch + last-frame write. **Done when:** suite green.

## V4.2 — Frontend I2V

**Files:** `frontend/src/components/videolab/*` (composer + gallery), `client.ts`,
`ImageLabPage.tsx`/`GenerationsPanel.tsx` (one small addition — see below).

- Composer: "+ Add start image" (file input, client-resize ≤1280 px longest side — reuse
  imageLab's resize helper), attachment chip with thumbnail + ×.
- Video cards: "Continue" action → pre-loads that job's `last_frame_b64` as start image.
- **Cross-lab Animate:** imageLab's `GenerationsPanel` gains an "Animate ▶" button per done
  image job that navigates to Video Lab with `{init_image_job_id}` staged (router state or a
  small shared store — follow existing navigation patterns). This is the ONLY imageLab file
  edit in the whole videoLab plan; keep it additive and tiny.
- Warm/cold both supported (params flow identically).

**Gate:** build clean; animate-from-upload and animate-from-imageLab work live or mocked.

## V4.3 — Second model: `ltxv` (fast tier)

**Files:** `video_models.py` (one row), new `kaggle_templates/video_ltxv/notebook.ipynb` +
`video_ltxv_session/notebook.ipynb`, dataset doc if no public weights dataset exists.

- LTX-Video distilled (~2B, `Lightricks/LTX-Video` Diffusers-native): few-step generation,
  minutes-per-clip on T4 — the "draft fast" option next to wan5b's "balanced". T2V + I2V.
- Notebooks are the wan5b templates with a different load cell + defaults (LTXV native
  resolutions — use its recommended dims closest to 9:16; keep 8n+1 snapping). Cell 0 stays
  byte-identical (template test enforces).
- Registry row carries its own timeouts (shorter run, faster load) and defaults. **Zero
  backend logic changes** — if any logic change is needed, that's a registry design bug to
  fix, not special-case.

**Tests:** template tests extended; registry row test. **Done when:** UI shows a second panel
(automatic via `/video/models`), live clip verified, real timings recorded in dev_log.

## V4.4 — Advanced params parity + live E2E

- `VideoAdvancedParams` exposes per-model knobs from registry defaults (steps, guidance,
  seed, negative prompt, WxH, fps where safe). Checkbox-opt-in pattern (imageLab IP-4).
- Live checklist: upload→animate, imageLab→Animate cross-lab, continue-from-last-frame,
  ltxv fast clip vs wan5b quality clip side by side. Docs updated.

---

## Risks

| Risk | Mitigation |
|---|---|
| LTXV weights/licensing quirks | LTXV license permits use with terms; note in registry row comment; dataset doc |
| Cross-lab coupling creep | single additive button in imageLab; all logic lives video-side |
| last_frame extraction bloats rows | it's one PNG b64 (~0.5–2 MB); excluded from list columns like video_b64 |
