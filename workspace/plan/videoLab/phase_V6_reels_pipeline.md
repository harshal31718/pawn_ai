# Phase V6 — Multi-Scene Reels Pipeline (DEFERRED — BEAM's Endgame)

**Status:** DEFERRED. Do not start until V1–V5 are live-verified and stable. This file
preserves BEAM's pipeline design translated into PAWN's architecture so the knowledge
survives; it is a design sketch, not numbered build steps — promote to steps when activated.

**Goal:** prompt + config → a 12–15 s, 9:16, multi-scene reel assembled from 4–6
continuity-linked clips, generated unattended on one warm session — BEAM's Definition of
Done, delivered through PAWN's UI instead of a bare notebook.

---

## What BEAM proved / designed (carried over)

- **One clip = one action.** Single clips doing transformations produce chaotic motion; reels
  must be scene-by-scene then stitched (BEAM's Phase-0 clip analysis — root cause confirmed).
- **Continuity = frame handoff:** end frame of scene N = start frame of scene N+1. V4 already
  banked `last_frame_b64` per job, and V5 banked FLF (start+end conditioning) — the two
  primitives this phase composes.
- **Layered design:** engine → scene → sequence → content-type → template → batch. New reel
  *types* = config + templates, not code.
- **Plain scene-loop + durable run state** beats a framework: BEAM deferred LangGraph in favor
  of a manifest file. PAWN equivalent: a `video_reels` table (reel row) + per-scene
  `video_jobs` rows linked by `reel_id`/`scene_index` — the DB *is* the run-state manifest;
  resumability = skip scenes whose job row is `done`.
- **LLM planning:** BEAM's Planner (scenes[] from prompt, strict JSON) + Prompt-expand
  (scene → cinematic prompt + negative). PAWN improvement: **route these through PAWN's own
  `normalize.chat_complete`** (BYOK, failover chains already built and battle-tested) instead
  of BEAM's hand-rolled Groq/Cerebras chain. Absolute rule: LLM calls go through
  `normalize.py` only.

## PAWN-shaped architecture sketch

```
POST /video/reel {prompt, type_config, model}          (routes/video.py)
  → reel row (planning) 
  → Planner via normalize.chat_complete (strict JSON scenes[])
  → per-scene video_jobs rows (queued, reel_id, scene_index, FLF params)
  → warm session serve-loop consumes them IN ORDER (scene N+1 waits for N's last_frame)
      — serve-loop addition: honor a `depends_on_job_id` column before claiming
  → stitch step: notebook-side ffmpeg concat on shared handoff frames + color normalize
      (BEAM stitch spec), producing reel.mp4 → reel row done
  → UI: ReelCard = scene strip (per-scene status/thumbnails) + final player
```

Open design questions to settle at activation time (record as decisions then):
1. Stitch location — notebook (has ffmpeg, has the clips) vs backend (needs clip download).
   Leaning notebook: clips never leave Kaggle until the final reel does. Reel MP4 (~15 s) may
   exceed comfortable base64 → this is the trigger to add the **Drive upload** result path
   (PAWN already has Drive storage layers to reuse).
2. Where scene templates/type configs live — `data/registry/`-style JSON (data, not code),
   consistent with PAWN's model registry philosophy. Seed with BEAM's fashion/morphsuit type
   (`docs/prompt_template.md` in BEAM repo) as the first content type.
3. Judge/best-of-N (BEAM Phase 7): GPU1 is free on every Kaggle box we rent — a VLM judge or
   T2I keyframe generator can run there. Defer both; design the serve-loop so a second-GPU
   worker cell is additive.
4. Keyframe generation for scene starts (BEAM used FLUX on GPU1): PAWN can instead route to
   **imageLab warm sessions** (cross-lab job: reel planner submits image_jobs for keyframes,
   then video scenes conditioned on them). Elegant reuse — but watch the 2-GPU-session cap;
   may require sequential phases (keyframes first, then video session).

## Prerequisites checklist (all delivered by V1–V5)

- [x-when-V4] `last_frame_b64` on every done job
- [x-when-V5] FLF conditioning (`wan14b`)
- [x-when-V2] long-liveness warm sessions with in-generation heartbeats
- [ ] Drive-upload result path for large artifacts (activate with this phase)
- [ ] `depends_on_job_id` serve-loop ordering (activate with this phase)
