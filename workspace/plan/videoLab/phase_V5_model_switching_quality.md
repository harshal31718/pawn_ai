# Phase V5 — Quality Tier: Wan2GP Engine, Wan2.2-14B FLF, LTX-2 22B

**Goal:** the Tier-2 engine — Wan2GP + mmgp Profile 4 + GGUF — added as registry rows, giving
videoLab its quality ceiling: Wan2.2 14B I2V/**FLF** (first+last frame conditioning — the key
primitive V6's reels need) and optionally LTX-2 22B Distilled. This is where BEAM's hardest-won
knowledge pays off; every setup landmine is already catalogued in `01_research_models.md` §4.

**Read first:** `01_research_models.md` §4 (Wan2GP headless API + landmines — treat as spec),
BEAM `docs/state.md` "Resolved setup issues" + "Headless API" sections if mounted (reference
only).

**Branch:** `dev`. Steps V5.1–V5.4 in `build_tracker.md`.

---

## V5.1 — Wan2GP notebook template family

**Files:** new `kaggle_templates/video_wan14b/notebook.ipynb` +
`video_wan14b_session/notebook.ipynb`; `scripts/kaggle_dataset_wan14b.md` (weights publish
doc: `wan2.2_14b_i2v_flf_gguf_q4_k_m` → private dataset, BEAM Phase 1b flow).

Structure (transplanted from BEAM's verified notebook, adapted to PAWN's cell-0 contract):
- Cell 0: byte-identical PostgREST helper block (template test enforces).
- Cell 1 (`installing`): env hygiene (`expandable_segments`, tokenizers off) → **full** clone
  of Wan2GP (never `--depth 1`) → `pip install -r requirements.txt` with torch pins stripped
  (KEEP_KAGGLE_TORCH-style filter; keep Kaggle default torch) → `numpy==1.26.4 scipy==1.13.1`
  pins → HF_HOME + `Wan2GP/ckpts` symlinks → `/kaggle/tmp`.
- Cell 2 (`loading_model`): dataset→ckpts symlink loop (BEAM's snippet), then
  `shared.api.init(cli_args=['--profile','4','--attention','sdpa','--gpu','cuda:0'])` →
  `ready`. Warn-don't-crash if dataset missing (falls back to auto-download with a loud
  `[pawn]` warning — acceptable in dev only).
- Serve loop: identical PostgREST job loop as wan5b session, but generation =
  `session.submit_task(settings)` where settings are built from job params: prompt, 704×1280,
  frames 8n+1, seed, `image_prompt_type` 'S'/'E'/'B' + `image_start`/`image_end` for
  I2V/FLF (write init/end images from b64 params to temp files first). `job.result()` →
  mp4 path → b64 → patch done (+ last_frame_b64).
- Generation heartbeat thread (V2.2 pattern) — clips run 12–18 min; also per-model
  `VIDEO_SESSION_*` overrides: registry rows gain optional
  `heartbeat_stale_seconds`/`startup_timeout_seconds` fields consumed by
  `video_session.py` (wan14b: stale 1800, startup 2400 — Wan2GP install alone is minutes).
  Add these registry fields + plumbing as the first commit of this step.

**Tests:** template tests (cell-0 identity, no torch pin, full-clone flag greps, symlink
loop present); registry override plumbing unit tests. **Done when:** green.

## V5.2 — `wan14b` registry row + FLF params

**Files:** `video_models.py`, `routes/video.py`, `video_jobs.py`/`video_session.py`, tests.

- Row: `engine="wan2gp"`, `supports_flf=True`, own timeouts/overrides, dataset ref.
- Params gain `end_image_b64`/`end_image_job_id` (resolved by the same `_resolve` helper,
  same ownership guards) — only accepted when the model row has `supports_flf`; 400 otherwise.
- Cold path for wan14b is allowed but the UI copy must warn it's ~30–45 min end-to-end
  (install+load dominates); warm session is the intended mode.

**Tests:** FLF param validation matrix; end-image resolution. **Done when:** suite green.

## V5.3 — UI: engine-aware polish (no new architecture)

**Files:** `frontend/src/components/videolab/*`.

- Panels appear automatically from `/video/models`. Add per-model registry-driven UI hints:
  speed badge ("fast ~3 min" / "balanced ~9 min" / "quality ~15 min" — from V4.3/V5.4
  measured timings), and an "End frame" attachment slot rendered only when `supports_flf`.
- Model descriptions/tooltips: one-liner per row served by `/video/models` (add `blurb` field
  to registry). Nothing hardcoded in the frontend.

**Gate:** build clean; FLF slot renders only on wan14b panel.

## V5.4 — Live verification + (optional) `ltx2` row

- Live warm wan14b session: I2V clip from an imageLab image; FLF clip (start+end frames) —
  confirm Wan2GP FLF wiring live (BEAM flagged it "confirm on first run"). Record timings.
- OPTIONAL (skip if weekly GPU quota is tight): add `ltx2` (LTX-2 22B Distilled GGUF) as a
  fourth row using the same template family — BEAM Phase 0 verified this exact model+engine
  on 1×T4. It's one registry row + one dataset doc + model_type
  `ltx2_22B_distilled_gguf_q4_k_m` in settings.
- Update `01_research_models.md` with measured T4 timings table; docs updated.

---

## Risks

| Risk | Mitigation |
|---|---|
| Wan2GP breaking changes since BEAM | pin Wan2GP to a known-good commit hash in the notebook (record in registry row comment); bump deliberately |
| FLF wiring unverified in Wan2GP | explicit live check in V5.4; fall back to I2V-only (supports_flf=False) if refuted — UI adapts automatically |
| Long installs eat session time | per-model startup timeout overrides; weights from dataset; consider a pre-built pip cache dataset later (backlog) |
| Q4 quality disappoints | quality levers documented: steps 8→12, Q6 dataset variant as sibling row |
