# Phase P7 — Characters (Soul-ID-like) & Lipsync Studio

**Goal:** persistent characters that stay consistent across clips and reels — Higgsfield's
Soul ID equivalent — plus a lipsync studio aggregating hosted lipsync models. Last phase
because it stands on everything: P2 (api features), P3 (LoRA training), P4 (references),
P6 (reels that need consistent casts).

**Read first:** `01_research_stack.md` §5, P3.4 LoRA plumbing, P4.3 reference slots.

**Branch:** `dev`. Steps P7.1–P7.4.

---

## P7.1 — Character library

**Files:** migration (`video_characters`: id, user_id, name, description, ref_image_refs
(Drive), lora_ref nullable, created_at), `core/video_characters.py`, routes, library UI.

- Character = named asset: 3–10 reference images (upload or from imageLab generations —
  cross-lab again), optional trained LoRA, usage notes (auto-appended prompt descriptor).
- Composer/ReelComposer gain a "Cast" slot: pick character → reference image + descriptor +
  LoRA (when backend supports) auto-applied. Per-scene cast in reels.
- Consistency mechanism per tier: api → native reference/character features (P4.3 mapping);
  gpu → LoRA + VACE reference.

**Tests:** CRUD + ownership, application matrix per backend/model capability.

## P7.2 — LoRA training jobs

**Files:** `workers/comfy/workflows/train_character_lora.json` (or ai-toolkit-based trainer
image variant — decide at build; ComfyUI-native preferred for one-image simplicity),
`gpu_exec` `train_lora` stage (P3.4 skeleton → real), UI "Train consistency LoRA" on the
character page.

- Input: character's reference images (augmented server-side: crops/flips) → LoRA to the
  user's volume + `lora_ref` on the character. Est cost shown (~$0.5–2 on A100/L40S,
  minutes). Retrain versioned (`lora_ref` history in provider_meta).
- Jugad note: training can run on spot/community-cloud rows (cheapest) — interrupted
  training is retryable, unlike serving.

**Tests:** stage wiring, versioning, budget stop; live gate: one character trained + used
in a Wan A14B generation showing consistency vs no-LoRA baseline (archive the A/B).

## P7.3 — Lipsync studio

**Files:** registry rows (`lipsync-*` — hosted models on fal: InfiniteTalk-class, Kling
Avatar-class, Veo-native where applicable), `api_exec` stage `lipsync`, small studio UI.

- Input: a video (any gallery clip or upload) + audio (upload / TTS via a hosted TTS row —
  optional) → lipsynced artifact. Per-model quality/price badges (Higgsfield's 10-model
  studio pattern, ours registry-driven).
- Ships as a tab on the character page + an action on gallery cards ("Make it talk").

**Tests:** stage param mapping, ownership of source artifacts.

## P7.4 — Live verification + 2.0 closeout

- E2E showpiece: create character from 5 imageLab portraits → train LoRA → 3-scene reel
  with that character on Max pipeline → lipsync the closing scene. Archive artifacts.
- Closeout: update `01_research_stack.md` prices/timings measured across P2–P7; write
  `v2/retrospective.md` (what matched Higgsfield, what still lags, backlog); promote
  anything deferred into `workspace/plan/plan_open_issues` style tracking.

---

## Risks

| Risk | Mitigation |
|---|---|
| Identity drift across models | per-model consistency mechanism matrix; prefer single-model casts within a reel |
| Face/likeness misuse | characters are user's own uploads; existing upload rules apply; no public-figure preset characters shipped |
| LoRA training variance | fixed training recipe + versioning + A/B gate before a LoRA becomes the character default |
