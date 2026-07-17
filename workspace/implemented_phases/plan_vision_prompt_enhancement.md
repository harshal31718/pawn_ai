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

## 2. Current state — items 1-4 SUPERSEDED 2026-07-16, shipped by F-11

Re-verified against code on 2026-07-16: F-11 (chat's image-attach feature,
shipped after this plan was drafted) already built the exact multimodal
plumbing items 1-4 called out as gaps. Nothing left to build for the
plumbing layer itself — only imageLab's own `vision_enhance.py` chain
(§3.2) and wiring (§3.4) are still net-new. Kept below for history/citation,
struck through where done:

1. ~~No multimodal support in the LLM plumbing today.~~ **Done.**
   `direct_answer_node` (`backend/app/agent/graph.py:180-215`) builds an
   OAI-style multimodal `content: [{"type":"text",...},
   {"type":"image_url","image_url":{"url": "data:image/...;base64,..."}}]`
   message today for image-attached chat turns. `chat_complete` passes
   `content` through untranslated (no provider-specific handling needed,
   confirming §3.1's original passthrough assumption).
2. ~~No vision-capable Groq model is registered today.~~ **Done.** `llama-4-scout`
   (`meta-llama/llama-4-scout-17b-16e-instruct`, endpoint id
   `ep-llama-4-scout-groq`, `data/registry/endpoints.json:297-309`,
   `last_verified: 2026-07-15`) is live, `supports_vision: true` in
   `models.json`.
3. **Gemini is already multimodal-capable** via the same OAI-compat endpoint
   (`gemini-2.5-flash`/`gemini-2.5-pro`/`gemini-3-flash`, provider `google`,
   all `supports_vision: true` in `models.json`) — unchanged from the
   original note, now additionally confirmed live via F-11.
4. ~~`ModelEntry` has no vision-capability flag.~~ **Done.**
   `registry/schemas.py:15` — `supports_vision: bool = False`. Resolver
   filters on it via `require_vision` (`resolver/resolver.py:130-153`),
   exactly the `require_tools` pattern this plan called for.
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

## 5. Open questions — RESOLVED 2026-07-16

All three blockers below are already closed by code shipped for F-11 (chat's
image-attach feature), which landed after this plan was first drafted. §3.1's
"no multimodal plumbing exists" premise is now stale — the plumbing exists;
only the imageLab-specific `vision_enhance.py` chain + wiring is still net-new.

1. **Groq vision model id — resolved, already registered.** `llama-4-scout`
   (`meta-llama/llama-4-scout-17b-16e-instruct`) is live on Groq,
   `endpoints.json` id `ep-llama-4-scout-groq`, `last_verified: 2026-07-15`,
   `supports_vision: true` in `models.json`. No fresh `registry-refresh`
   needed to unblock this plan.
2. **Applies to every generation, both text-only and image+text — resolved,
   confirmed.** Matches the original request's "when we take image or/and
   prompt" and Q3.1's default-on design.
3. **Provider-pinning mechanism — resolved, reuse the F-11/F-6 pattern
   exactly.** `ROLE_LEVELS["vision_answer"] = "balanced"` +
   `resolver.pick_model_by_capability(level, require_vision=True)`
   (`constants.py:141-146`, `resolver/resolver.py:130-153`) already does
   "pick a vision-capable model" for chat. §3.2's `enhance_with_vision`
   should add its own `ROLE_LEVELS["vision_enhancer_primary"]` entry and
   call the same resolver method — no new mechanism, no `prefer_provider`
   param needed. Groq-first-then-Gemini is expressed as two sequential
   `pick_model_by_capability(require_vision=True)` calls scoped to
   provider="groq" then unscoped, not a single call with provider
   preference baked in (mirrors how F-11 itself has no explicit
   Groq-vs-Gemini ordering need — this plan's chain is one level more
   specific than F-11's, so it can't reuse F-11's call site, only its
   underlying resolver capability).

## 6. Suggested integration with existing plans

- Update `imageLab/phase_Q3_prompting_presets.md` Q3.1 to point here for the
  LLM-call mechanics (vision-aware, Groq→Gemini→raw chain) — its per-model
  research (SDXL keyword-scaffold vs FLUX natural-language) is unchanged and
  feeds this plan's §3.3.
- Suggested build order: §3.1 (multimodal plumbing + registry vision flag) →
  §3.2 (provider-chain helper) → §3.3 (schema fields, imageLab) → §3.4.
  §3.5 (videoLab reuse) waits until videoLab is picked back up.
