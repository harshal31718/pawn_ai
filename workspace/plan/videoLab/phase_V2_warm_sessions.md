# Phase V2 — Warm Sessions: Serve-Loop, Timers, Lifecycle

**Goal:** the imageLab warm-session experience for video — start a session, model loads once,
many clips generated in-session, live countdown timer, extend, stop, heartbeats, startup-phase
visibility, dead-session detection. Video makes warm sessions MORE valuable than for images:
Wan2.2-5B load is ~12 GB of weights, and per-clip time (~9 min) means heartbeat/staleness
tuning is the critical difference from imageLab.

**Read first:** `backend/app/core/image_session.py` (the file being mirrored),
`backend/app/kaggle_templates/image_sdxl_session/notebook.ipynb`,
`workspace/plan/plan_imagelab_session_issues.md` (dead-session detection — all of it applies),
`workspace/implemented_phases/phase_05_kaggle_image.md` §Known Issues (the heartbeat cascade).

**Branch:** `dev`. Steps V2.1–V2.4 in `build_tracker.md`.

---

## V2.1 — `video_sessions` table + session core

**Files:** new `postgres/migrations/2026-07_video_sessions.sql`, `postgres/schema.sql`,
new `backend/app/core/video_session.py`, `backend/app/constants.py`.

- Table mirrors `image_sessions` (id, user_id, model, kernel slug, status, heartbeat_at,
  expires_at, stop_requested_at, created_at) — plus nothing video-specific needed.
- `video_session.py` mirrors `image_session.py`'s full lifecycle:
  `start_session`, `extend_session`, `stop_session`, `get_session_status`,
  `submit_session_job` (inserts into `video_jobs` with `session_id`), `reap_stale_jobs`,
  `_is_alive`, `_kernel_probe` (the round-7 dead-session detection — throttled Kaggle
  `/kernels/status` probe wired into the warmup branch; transplant it, don't re-derive it).
- **Video-tuned constants** (new VIDEO_ block in `constants.py`; DO NOT touch IMAGE_ values):

```python
VIDEO_SESSION_HEARTBEAT_STALE_SECONDS = 900   # ≥1.5× worst-case per-clip gen (~9–10 min);
                                              # imageLab's 90 s would false-kill every job
VIDEO_SESSION_STARTUP_TIMEOUT_SECONDS = 1800  # 12 GB weights from mounted dataset + install
VIDEO_SESSION_KAGGLE_PROBE_INTERVAL_SECONDS = 30
VIDEO_SESSION_STARTUP_PROBE_AFTER_SECONDS = 60
VIDEO_SESSION_RUNNING_NO_HEARTBEAT_TIMEOUT_SECONDS = 1200
VIDEO_SESSION_MAX_DURATION_MINUTES = 120
```

  imageLab's #1 live bug was heartbeat-staleness killing jobs mid-inference (30 s threshold vs
  30–90 s inference). Video inference is ~9 min — the notebook must ALSO heartbeat **from a
  background thread during generation** (see V2.2), so staleness detection stays meaningful
  instead of relying on a huge threshold alone. Both defenses go in.
- Cold-vs-warm routing guard (imageLab W.6 Fix B): `create_cold_job` in `video_jobs.py`
  refuses when a live warm session exists for that model. Cross-modality note: Kaggle's
  2-GPU-session cap is GLOBAL per account — an imageLab warm session + a videoLab warm
  session = the cap. `start_session` must surface the existing human-readable GPU-limit
  error; additionally check for live **image** sessions and include them in the message
  ("Your FLUX warm session counts toward Kaggle's 2-GPU limit").

**Tests:** new `backend/tests/test_video_session.py` — lifecycle, `_LIVE_STATUSES`
(`starting/installing/loading_model/ready` from day one — imageLab's W.4 bug pre-fixed),
staleness with monkeypatched time, probe throttling, cold-block-when-warm, GPU-limit
message includes cross-modality sessions. **Done when:** suite green.

## V2.2 — Warm serve-loop notebook (`video_wan5b_session`)

**Files:** new `backend/app/kaggle_templates/video_wan5b_session/notebook.ipynb`,
`backend/app/core/video_models.py` (fill `session_template`/`session_slug`).

Mirror `image_sdxl_session/notebook.ipynb` cell-for-cell:
- **Cell 0 byte-identical** to the image session templates' cell 0 (PostgREST helpers,
  never-raising `_rest_patch` with retry + `[pawn]` log lines + 0-row-write detection).
  Extend `test_kaggle_session_templates.py` to enforce byte-identity across image AND video
  session templates together.
- Cell 1: `patch_session({"status": "installing"})` first line; try/except-wrapped pip
  install (round-7 fix); env hygiene + HF_HOME→/kaggle/tmp.
- Cell 2: `patch_session({"status": "loading_model"})` → load pipeline once from mounted
  dataset → `patch_session({"status": "ready", ...})`.
- Serve loop: poll `video_jobs` for `queued` rows (this session's model+user), claim →
  `running` + `started_at`, generate, H.264-encode with size guard, patch `done` +
  `video_b64` + result metadata (`duration_s/fps/width/height`).
- **Generation-time heartbeat thread**: a daemon thread patches `heartbeat_at` every 60 s
  *including while the pipeline call is running* (this is the new-vs-imageLab piece; images
  were fast enough to skip it). Supervisor keeps the round-7 fixes: heartbeat decoupled from
  read success, 600 s total-unreachability self-exit (`os._exit(1)`).
- Honor `stop_requested_at` (poll it; exit cleanly), session `expires_at`, params from job
  row: `negative_prompt`, `width/height`, `num_frames` (snap 8n+1 notebook-side too —
  defense in depth), `steps`, `guidance`, `seed`, and `init_image_b64` (accepted from day
  one — TI2V is I2V-native; UI wires it in V4).

**Tests:** template tests (cell-0 identity, warmup short-circuit, no secrets, heartbeat
thread present via source grep, `os._exit` self-exit present). **Done when:** green.

## V2.3 — Session routes

**Files:** `backend/app/routes/video.py`.

Mirror imageLab's session surface: `POST /video/session/start`, `GET /video/session/status`,
`POST /video/session/job`, `POST /video/session/stop`, `POST /video/session/extend`.
Same request models, same threadpool discipline, same typed-error mapping. Status response
carries `status` + substatus phases + `expires_at` so the UI can render
"Warming · loading model · 3m 12s" and the live countdown (imageLab round-7 UI parity).

**Tests:** extend `test_video_routes.py` — start/status/job/stop/extend happy paths +
extend-past-max clamped + stop idempotent. **Done when:** suite green.

## V2.4 — Live verification (user's creds; record timings)

- Start warm wan5b session → observe `starting → installing → loading_model → ready` in
  status API; record each phase's real duration in `dev_log.md` (calibrates V3's UI copy,
  like imageLab's "FLUX: ~7 min" hint).
- Submit 3 jobs back-to-back → all complete without false "session ended" (the heartbeat
  thread + 900 s threshold prove out); countdown/extend/stop each verified.
- Stop → kernel exits promptly (stop_requested honored), no orphaned GPU session on Kaggle.

**Done when:** all above observed live; docs updated.

---

## Risks

| Risk | Mitigation |
|---|---|
| False dead-session kills mid-clip (imageLab's #1 bug, worse for video) | in-generation heartbeat thread + 900 s threshold + kernel probe |
| Kaggle 2-GPU cap collisions with imageLab sessions | cross-modality check in start_session + clear error copy |
| 12 h background cap mid-session | MAX_DURATION 120 min default, extend explicit, expires_at enforced notebook-side |
| Big base64 PATCHes fail silently | cell-0 `_rest_patch` 0-row/oversize detection + 50m body limit (V1.5) |
