# Phase P4 — Cinematic Control Suite: Presets, Camera, References

**Goal:** Higgsfield's signature layer — 50–100+ cinematic presets (camera moves, motion
styles, VFX looks) that apply across EVERY model/backend, plus reference-image conditioning
and (gpu tier) real control via VACE + camera LoRAs. This is what turns "a text-to-video
wrapper" into a director's tool.

**Read first:** `01_research_stack.md` §5, Higgsfield's public preset taxonomy (camera-controls
page) as the naming benchmark, P2 registry, P3 workflow param plumbing.

**Branch:** `dev`. Steps P4.1–P4.4.

---

## P4.1 — Preset registry

**Files:** new `data/registry/video_presets.json`, new `core/video_presets.py` (load,
validate, compose), `routes/video.py` (`GET /video/presets`), tests.

Preset = data, three layers of application (strongest available wins per model):

```json
{
  "id": "crash_zoom_in",
  "category": "camera",            // camera | motion | vfx | style | shot
  "label": "Crash Zoom In",
  "blurb": "Aggressive fast push toward subject",
  "prompt_fragment": "sudden aggressive crash zoom in toward the subject, motion blur, ...",
  "negative_fragment": "static camera",
  "model_overrides": {
    "kling":   {"params": {"camera_control": {"type": "zoom", "speed": "fast"}}},
    "wan14b-hd": {"lora": {"ref": "loras/wan_crash_zoom.safetensors", "strength": 0.8},
                   "vace": null}
  },
  "conflicts_with": ["slow_dolly_in", "static_shot"],
  "preview_ref": "presets/crash_zoom_in.mp4"
}
```

- Composition rules in `video_presets.py`: max 1 camera + 1 motion + N style presets;
  conflict validation; fragments appended server-side (canonical prompt stored on the job —
  imageLab STYLE_SUFFIXES rule, generalized).
- **Seed library: 40–60 presets** authored in this step across categories — camera (dolly
  in/out, orbit L/R, crane up/down, FPV, handheld, crash zoom, bullet time, static,
  tracking), motion (slow-mo feel, timelapse, walk cycle), shot (close-up, wide,
  over-shoulder, low angle), style (cinematic teal-orange, film grain 35mm, noir, golden
  hour, product studio), vfx (explosion bloom, rain, snow, lens flare). Write them from
  Higgsfield's taxonomy + Wan camera-control prompt grammar research; iterate from results.

**Tests:** schema validation of every shipped preset, conflict matrix, composition output.

## P4.2 — Composer UI: preset browser

**Files:** `frontend/src/components/videolab/PresetBrowser.tsx` (+ chips row upgrade).

- Chips row (V3) becomes category-tabbed preset browser: horizontal scroll rows per
  category, selected presets render as removable chips on the composer; conflicts
  auto-deselect with a toast. Hover/tap = preview clip when `preview_ref` exists (generate
  previews lazily with the cheapest draft model — a nice dogfooding batch job).
- Mobile: bottom-sheet browser, search box, 44px targets.

**Gate:** build clean; preset → job params verified against backend composition tests.

## P4.3 — Reference images + start/end frames everywhere

**Files:** `api_exec.py` param mapping, workflow JSONs, composer.

- Start-frame (I2V) already flows (V4); add per-model mapping for **reference/character
  image** (Kling/Seedance reference features; Veo ingredients; gpu tier → VACE reference
  input) — one composer slot "Reference" with per-model capability from registry
  (`supports_reference_image`), plus end-frame slot where supported (FLF rows).
- Cross-lab hooks extend: "Use as reference" on imageLab cards.

**Tests:** capability-gated validation (400 on unsupported), param mapping per provider.

## P4.4 — GPU-tier real control (VACE) + live preset calibration

- Workflow `wan22_vace` : pose/depth/reference conditioning inputs wired (P3.4 plumbing);
  composer exposes it as "Control: pose from video / depth / reference" advanced section
  (gpu tier only).
- **Calibration pass (the quality step):** run a fixed benchmark prompt through every camera
  preset on Draft + one Pro model; eyeball + judge-score (P6 preview) the adherence; tune
  fragments/params; store the benchmark set under `workspace/plan/videoLab/v2/benchmarks.md`
  with observations. Presets are only as good as their calibration — budget ~$5–10 of API
  spend for this pass.

---

## Risks

| Risk | Mitigation |
|---|---|
| Prompt-only presets weak on some models | three-layer design (params > lora/vace > prompt); calibration pass drops weak combos per model via `model_overrides` |
| Preset sprawl/quality drift | registry schema validation + benchmark file as regression baseline |
| Preview generation cost | lazy, draft-tier, cached in Drive; skip previews on tight budget |
