# Plan: Vision-Grounded Prompt Enhancement (imageLab)

**Status:** PLANNED — plan only, no code written. **Branch:** `dev`.
**Date:** 2026-07-15, from the user's request. **Re-scoped 2026-07-16: build order
is chat → imageLab; videoLab is deferred to the very end and out of scope for this
plan until then** — the design below is written for imageLab only. (It was originally
drafted as shared plumbing with a since-deferred videoLab plan; anything below that
still mentions that lab is a parked note for whenever videoLab is picked back up, not
active scope.) Read alongside
`workspace/plan/imageLab/phase_Q3_prompting_presets.md` (Q3.1) — this plan **extends
and supersedes that enhancer section** rather than duplicating it; it should be
updated to point here once this is approved (see §6).

## 1. What was asked for

- When the user supplies an image and/or a prompt (imageLab's existing img2img
  path — `init_image_b64`, `routes/generate.py`), send both to an image+text
  (vision) model. It analyses the image and the prompt together and returns a
  refined/updated prompt.
- That refined prompt (plus the original image, for img2img) is then sent to
  the actual generation model (SDXL/FLUX today) as normal.
- If the vision call errors or is unavailable, fall through to the raw
  (unenhanced) prompt — generation must never block on this step.
- Provider chain for the vision call: **Groq first (default) → Gemini if Groq
  unavailable → raw prompt if neither works.**
- Prompt **schemas** (the shape of what gets asked for/returned, and the style
  of prompt each target generation model wants) should be optimal per the
  generation model actually being used (SDXL vs FLUX), not one-size-fits-all.
  (A future videoLab pass would need its own Wan/Kling-class schemas — deferred,
  not designed here.)

## 2. Current state (verified against code, 2026-07-15) — real prerequisite gaps

1. **No multimodal support in the LLM plumbing today.** `llm_core.chat_complete`/
   `normalize.chat_complete` (the only sanctioned path per `.claude/CLAUDE.md`
   rule #1) send plain-text `messages` — there is no code path anywhere that
   builds an OAI-style multimodal `content: [{"type":"text",...},
   {"type":"image_url","image_url":{"url": "data:image/...;base64,..."}}]`
   message. This has to be added before any image-aware enhancement can work
   at all.
2. **No vision-capable Groq model is registered today.** Every Groq endpoint
   in `data/registry/endpoints.json` (`llama-3.3-70b`, `gpt-oss-120b`,
   `deepseek-r1-distill`) is text-only. Groq's free tier does offer
   vision-capable models (e.g. a Llama-4 Scout/Maverick-class multimodal
   model, or a Llama-3.2-vision-class model at the time of writing — confirm
   the exact currently-live Groq model id via `registry-refresh` before
   building, since Groq's free-tier vision lineup changes). None of this
   exists in the registry yet — it's a new row, not a flag flip.
3. **Gemini is already multimodal-capable** via the same OAI-compat endpoint
   (`gemini-2.5-flash`/`gemini-3-flash`, provider `google`) — no new
   registration needed there, just the multimodal-content plumbing from
   item 1.
4. **`ModelEntry` has no vision-capability flag.** Mirrors the existing
   `supports_tools: bool` pattern (`registry/schemas.py:19`-ish) — a new
   `supports_vision: bool = False` field is needed so the resolver can filter
   for it, the same way `require_tools` works today in
   `pick_model_by_capability`.
5. **imageLab's own Q3.1 already half-specs a text-only enhancer** (`enhance(
   prompt, model_row, style_preset) -> {prompt, negative}` via
   `normalize.chat_complete`, per-model `prompt_style` field) — this plan
   makes it vision-aware (image optional input) and formalizes the
   Groq→Gemini→raw chain Q3.1 left unspecified (Q3.1 just says "fast tier",
   no fallback chain).

## 3. Proposed design

### 3.1 Shared multimodal plumbing (new, prerequisite for everything else)

- `llm_core.chat_complete` gains the ability to accept messages whose
  `content` is either a plain string (unchanged, current behavior) or a list
  of OAI-style content parts (`text` / `image_url`) — passthrough only, no
  provider-specific translation needed since every provider here already
  speaks the OAI-compatible wire format (per this repo's own house rule).
- `normalize.chat_complete` — no signature change needed beyond what already
  exists; multimodal content just flows through in the `messages` param.
- `ModelEntry.supports_vision: bool = False` (`registry/schemas.py`), set
  `true` on Gemini rows and the new Groq vision row;
  `resolver.pick_model_by_capability` gains `require_vision: bool = False`
  (mirrors the existing `require_tools` param exactly).

### 3.2 Provider chain helper (new)

New `backend/app/core/vision_enhance.py` (or similar; exact module home is a
build-time call):

- `enhance_with_vision(prompt, image_b64, target_model_schema, user_id,
  resolver, rate_limiter) -> {prompt, negative, used_model, degraded}`.
- Tries, in order: (1) a Groq model with `supports_vision=True` via
  `pick_model_by_capability(..., require_vision=True)` filtered to
  provider="groq" (or a dedicated `ROLE_LEVELS["vision_enhancer_primary"]`
  role level pinned to Groq's vision row specifically, if capability-level
  filtering can't express "this provider first" cleanly — a build-time call,
  same shape as F-6's groq-priority problem); (2) a Gemini vision model on
  any failure (no Groq key, rate-limited, malformed response, timeout); (3)
  **on both failing, returns the raw prompt unchanged** (`degraded=True`,
  `used_model=None`) — generation proceeds exactly as it does today. Never
  raises — mirrors A.2's `run_tool` never-raise contract.
- Text-only path (no image supplied): same function, `image_b64=None` — still
  goes through the same Groq→Gemini→raw chain, just without the image content
  part. This is what imageLab's no-img2img-reference case uses.

### 3.3 Per-target-model prompt schemas (formalized, not free-text)

Replace Q3.1's vague "system prompts stored on the registry row" with an
explicit schema object per generation model, so the enhancer's instructions
and output shape are structured, not just a prose system prompt:

```
PromptSchema:
  format: "keyword_scaffold" | "natural_language" | "cinematic_grammar"
  max_length: int | None
  wants_negative: bool
  vocabulary_hints: list[str]   # camera/lens/lighting/texture words, or
                                # cinematic-grammar terms for video models
  system_prompt: str            # the actual enhancer instruction, built from
                                # the fields above at registration time (single
                                # source of truth — don't hand-author both a
                                # schema AND a separate free-text prompt that
                                # can drift out of sync)
```

- imageLab (`core/image_models.py`'s `ImageModel` dataclass): new
  `prompt_schema: PromptSchema` field.
  - SDXL: `format="keyword_scaffold"`, `wants_negative=True`,
    `vocabulary_hints=[camera/lens/lighting/texture/film words — from Q1's
    research]`.
  - FLUX: `format="natural_language"`, `wants_negative=False` (FLUX-schnell's
    distilled pipeline doesn't use negatives — matches Q1.4's existing
    finding), `vocabulary_hints=[realism descriptors]`.
- The vision-enhancer's own system prompt for the *analysis* step (what it
  tells the vision model to look for when given an image) is separate from
  the *target* schema above — it should say roughly "describe what's
  visually present, then rewrite the user's prompt against the following
  target-model schema: {vocabulary_hints}, format={format}" — one shared
  analysis-prompt template, parameterized by the target schema, not a
  hand-authored prompt per model pair.

### 3.4 Wiring into imageLab

- `routes/generate.py`: when `init_image_b64` is present (or even for a
  text-only prompt — enhancement applies either way per §3.2), call
  `enhance_with_vision(prompt, init_image_b64, IMAGE_MODELS[model].prompt_schema,
  ...)` before building `params_dict`. Store both `original_prompt` and
  `enhanced_prompt` on the job (matches Q3.1's existing "both stored" rule).
  Composer UI: same "✨ Enhance" toggle Q3.1 already specs, editable before
  submit.
- Failure/degraded path: `params_dict["prompt"]` falls back to the raw
  user prompt, exactly as if enhancement were off — generation never blocks.

### 3.5 videoLab reuse (parked, not active)

videoLab is deferred to the very end (see `workspace/plan/README.md`) — not in
scope for this plan right now. When it's picked back up, the same
`enhance_with_vision` shape should apply to its own generate route, with the
reference image feeding the same vision-analysis path as imageLab's img2img.
Left as a note for that future session, not a build target here.

## 4. Tests (for whichever build-step session picks this up)

- `vision_enhance.py`: Groq-succeeds path, Groq-fails-Gemini-succeeds path,
  both-fail-returns-raw path (never raises), text-only vs with-image content
  shape, `require_vision` resolver filter positive/negative.
- `resolver.py`: `pick_model_by_capability(require_vision=True)` excludes
  non-vision rows.
- imageLab route test: enhanced prompt reaches the job params; raw prompt
  used when enhancement is toggled off or fails.
- No security-auditor needed beyond what A.1-A.3 already cover (same
  `chat_complete`/BYOK-key path, no new secret surface) — the only new
  surface is base64 image bytes flowing into an LLM call, which is
  content-not-secret; still worth a quick note to security-auditor at build
  time given it's a new kind of payload through that path.

## 5. Open questions before this is buildable

1. Exact currently-live Groq vision-capable model id/free-tier availability —
   needs a `registry-refresh`-style check at build time (Groq's model lineup
   changes; this plan intentionally doesn't hardcode one to avoid drafting
   against a stale target).
2. Does enhancement apply to *every* generation (default-on, per Q3.1's
   design), or only when an image is attached? The request says "when we
   take image or/and prompt" — read as: applies to both text-only and
   image+text cases. Confirm before building if that's not the intent.
3. Where does `require_vision`-style provider pinning to "Groq specifically,
   not just any vision-capable model" live cleanly — a new `ROLE_LEVELS`
   entry, a dedicated `prefer_provider` param, or is capability-level
   filtering alone sufficient? (Same open design question F-6 already raised
   for orchestrator-provider pinning — worth resolving once, reused by both.)

## 6. Suggested integration with existing plans

- Update `imageLab/phase_Q3_prompting_presets.md` Q3.1 to point here for the
  LLM-call mechanics (vision-aware, Groq→Gemini→raw chain) — its per-model
  research (SDXL keyword-scaffold vs FLUX natural-language) is unchanged and
  feeds this plan's §3.3.
- Suggested build order: §3.1 (multimodal plumbing + registry vision flag) →
  §3.2 (provider-chain helper) → §3.3 (schema fields, imageLab) → §3.4.
  §3.5 (videoLab reuse) waits until videoLab is picked back up.
