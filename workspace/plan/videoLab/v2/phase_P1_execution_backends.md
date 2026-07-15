# Phase P1 — Execution Backends, Artifact Store, Cost Ledger

**Goal:** the plumbing every other 2.0 phase stands on: a backend-pluggable executor layer
(`kaggle` becomes just one of three), Drive-based artifact storage for big outputs, and a
cost ledger with hard budgets. Zero new models in this phase — an existing wan5b Kaggle job
must run unchanged through the new abstraction (regression proof).

**Read first:** basic videoLab implemented code (`core/video_jobs.py`, `core/video_session.py`,
`routes/video.py`), `core/key_store.py`, `storage/drive.py` + `conversations_drive.py`
(Drive layer patterns), `00_overview_v2.md`.

**Branch:** `dev`. Steps P1.1–P1.4 in `build_tracker.md`.

---

## P1.1 — Schema v2 + executor interface

**Files:** migration `2026-XX_video_jobs_v2.sql`, `postgres/schema.sql`,
new `backend/app/core/video_exec/__init__.py` + `base.py` + `kaggle_exec.py`,
`core/video_jobs.py` (dispatch switch), `constants.py`.

- `video_jobs` gains: `backend text default 'kaggle'`, `pipeline_id uuid null`,
  `depends_on_job_id uuid null`, `stage text default 'generate'`
  (`generate|upscale|interpolate|audio|mux|train_lora|lipsync`), `artifact_ref text null`,
  `poster_b64 text null`, `est_cost_usd numeric null`, `actual_cost_usd numeric null`,
  `provider_meta jsonb default '{}'` (request ids, provider job urls — for support/debug).
- `video_exec/base.py`: `class VideoExecutor(Protocol)`:
  `estimate(job) -> CostEstimate`, `dispatch(job) -> None` (async, fire-and-forget semantics
  preserved), `poll(job) -> JobUpdate | None` (for pull-style providers), `cancel(job)`.
- `kaggle_exec.py`: wraps the existing cold/warm code paths behind the interface —
  **refactor by delegation, not rewrite**; existing functions stay, executor calls them.
  `estimate()` returns $0.00 always.
- Dispatch: `video_jobs.py` looks up executor by `job.backend` from a registry dict built in
  `app_initializer`.

**Tests:** executor protocol conformance for kaggle_exec; full existing video test suite
green UNCHANGED (the regression proof); new columns default correctly for old rows.

## P1.2 — Drive artifact store

**Files:** new `backend/app/storage/videolab_drive.py`, `core/video_jobs.py`,
`routes/video.py`, frontend `client.ts` + gallery lazy-load path.

- `PAWN/videolab/{job_id}/final.mp4` (+ `draft.mp4`, `frames/` later) via the existing
  DriveStorage; `save_artifact(user_id, job_id, bytes, name) -> artifact_ref`,
  `stream_artifact(...)` (ranged read for `<video>` seeking — implement HTTP Range support
  in a new `GET /video/artifact/{job_id}` route; Drive supports ranged download).
- Job completion path: executor writes artifact → sets `artifact_ref` + `poster_b64`
  (first frame, small) → `video_b64` stays NULL for 2.0 backends.
- Frontend: gallery card uses `poster_b64`; player streams from the artifact route (native
  `<video src>` with Range). Kaggle-tier jobs keep the base64 path untouched.
- Rule: users without Drive linked → 2.0 backends refuse with a clear "link Drive first"
  error (Drive is already mandatory-ish in PAWN — verify against phase_10 behavior).

**Tests:** artifact save/stream (mocked Drive), Range header handling, no-Drive error path.
Security-auditor: ranged route must enforce job ownership.

## P1.3 — Cost ledger + budgets

**Files:** migration (`video_spend` table), new `core/video_cost.py`, `routes/video.py`,
Settings UI section, composer estimate display (frontend).

- `video_spend`: user_id, job_id, backend, est/actual usd, created_at. Monthly rollup query.
- `core/video_cost.py`: `check_budget(user_id, est) -> raises BudgetExceededError`,
  `record(job, actual)`. `VIDEO_MONTHLY_BUDGET_USD_DEFAULT = 25.0`, per-user override stored
  in user settings; hard stop, no soft-warn-only mode.
- **Every executor's `dispatch()` MUST call `check_budget` first** — enforced by a shared
  pre-dispatch hook in `video_jobs.py` (single choke point), not per-executor discipline.
- UI: Settings shows month-to-date spend + budget editor; composer shows `≈ $X.XX` before
  submit (from `estimate()`); confirm dialog above a per-job threshold ($1 default).

**Tests:** budget stop (the mandatory spend-safety test), rollup math, estimate surfaces in
route response. Security-auditor mandatory (spend authority).

## P1.4 — Provider keys + verification

- `key_store.VALID_PROVIDERS` += `fal`, `replicate`, `runpod`, `modal` (+ Settings UI rows,
  "Video compute (optional)" group). Encrypted at rest like all BYOK keys.
- Live regression: one Kaggle wan5b clip end-to-end through the executor path; ledger row
  written ($0.00); artifact route smoke-tested with a manually-uploaded file.
- Docs updated (tracker/current_state/dev_log).

---

## Risks

| Risk | Mitigation |
|---|---|
| Refactor destabilizes live Kaggle path | delegation-only refactor + full suite green unchanged as explicit gate |
| Drive latency for playback | Range streaming + poster-first UX; measure; CDN-less is acceptable v1 |
| Budget race (parallel dispatches) | check+record inside one DB transaction; test with two concurrent jobs |
