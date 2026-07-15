# Phase P6 — Quality Orchestration: Enhancer, Draft→Final, Judge, Reels 2.0

**Goal:** the intelligence layer — automatic prompt enhancement, draft-then-final routing,
best-of-N with a VLM judge, and the multi-scene Reels pipeline reborn on 2.0 substrate
(supersedes basic plan's deferred V6). This is where PAWN's existing agent stack becomes a
video director.

**Read first:** `core/normalize.py` + `agent/` (LLM plumbing to reuse), basic plan
`phase_V6_reels_pipeline.md` (design carried over), P1 DAG, P2/P3 executors.

**Branch:** `dev`. Steps P6.1–P6.4.

---

## P6.1 — Prompt enhancer

**Files:** new `core/video_prompting.py`, `routes/video.py`, composer toggle, tests.

- `enhance(prompt, presets, model_row) -> {enhanced, negative}` via `normalize.chat_complete`
  (fast tier): expands terse prompts into model-appropriate cinematic grammar (per-model
  style guides as system-prompt snippets in the registry row — Kling likes X, Wan likes Y;
  seed from provider prompt guides + P4 calibration learnings). Preset fragments compose
  AFTER enhancement (presets stay authoritative).
- Composer: "✨ Enhance" toggle (default on for Pro/Max), shows the enhanced prompt
  editable before submit — never a black box. Enhanced + original both stored on the job.

**Tests:** composition order, opt-out path, failure = fall through to raw prompt (never
block generation on LLM failure).

## P6.2 — VLM judge

**Files:** new `core/video_judge.py`, registry (`judge` config), tests.

- `judge(job, criteria) -> {score, reasons}`: sample 4–6 frames from the artifact
  (ffmpeg server-side, cheap) → vision-capable model via `normalize.chat_complete`
  (BYOK vision model — reuse PAWN's model registry; Gemini-class works) → structured score:
  prompt adherence, motion sanity, artifact severity, preset adherence.
- Judge results stored on the job (`provider_meta.judge`); gallery shows score badge
  (subtle); manual "Judge this" action on any clip.
- This is BEAM Phase 7's design finally landing — frames-to-VLM instead of a self-hosted
  Qwen2-VL, because BYOK makes it a $0.001 call instead of a GPU tenancy.

**Tests:** frame-sampling determinism, structured-output parsing (strict JSON pattern from
BEAM's planner learnings), judge-failure = no-score (never blocks).

## P6.3 — Draft→final + best-of-N pipelines

**Files:** `core/video_jobs.py` pipeline builders, composer "Max" flow, tests.

- **Best-of-N draft:** N (default 3) seeds on `seedance-fast` in parallel → judge each →
  auto-select winner (user can override in a picker UI before the final render proceeds —
  configurable: auto-continue vs pause-for-pick, default pause on >$0.50 finals).
- **Final render:** winner's seed/prompt/params re-rendered on the Max model + P5 finishing
  chain. The full thing is one pipeline_id; the stage strip shows it all.
- Budget-aware: whole-pipeline estimate up front; judge/draft failures degrade gracefully
  (fewer drafts, or straight-to-final with a warning).

**Tests:** pipeline construction matrix, winner propagation (seed/params carry exactly),
pause-for-pick state machine, degradation paths.

## P6.4 — Reels 2.0 (multi-scene)

**Files:** new `core/video_reels.py`, `routes/video.py`, `ReelComposer` UI, tests.
Design basis: basic plan `phase_V6_reels_pipeline.md` — all of it carries over, with 2.0
upgrades:

- Planner via `normalize.chat_complete` (strict JSON scenes[]) — unchanged design.
- Scene continuity: last-frame handoff AND (api tier) native start-image conditioning on
  every Pro model; FLF where available. Character consistency via P7 references when set.
- Scenes are pipeline stages (`reel_id` = pipeline_id; scene N+1 `depends_on` scene N);
  stitch = `stage_mux` extension (concat + color normalize — BEAM spec); reel artifact to
  Drive. **No new orchestration machinery needed — the P1 DAG + P5 scheduler already carry
  it.** That's the payoff of the staged design.
- UI: ReelComposer (prompt + scene count + type template) + scene strip on the reel card
  (per-scene status/thumb/retry-scene action).
- Content-type templates in `data/registry/reel_types.json` (seed: BEAM's fashion/morphsuit
  template as homage + a generic "product showcase" + "travel montage").

**Tests:** planner JSON validation, scene DAG construction, per-scene retry, stitch params.
Live gate: one 12–15 s 4-scene reel on Pro tier; cost + time recorded.

---

## Risks

| Risk | Mitigation |
|---|---|
| Judge disagrees with human taste | judge advises, user picks (pause-for-pick default); calibration vs P4 benchmarks |
| Pipeline complexity explosion | everything is the same DAG primitive; no bespoke orchestrators; LangGraph explicitly NOT introduced (BEAM's lesson) |
| Reel scene drift (style/character) | shared enhanced-prompt prefix + reference image on every scene + P7 characters |
