# Phase Q3 — Prompting: Enhancer, Negatives, Preset Rework

**Goal:** the biggest free quality win — turn terse user prompts into photoreal-grade
prompts automatically, ship sane negative defaults, and rebuild style presets on the
research findings. Everything here is prompt-plumbing; no new weights except optional
negative embeddings.

**Read first:** `01_research_quality.md` §5, `plan_vision_prompt_enhancement.md` (the
vision-aware enhancer mechanics this section's Q3.1 defers to), `routes/generate.py`
(`STYLE_SUFFIXES`), `core/normalize.py` (LLM plumbing), `core/router.py` (the
heuristic-first/LLM-fallback pattern §3.1.4 below reuses).

**Branch:** `dev`. Steps Q3.1–Q3.4.

**Decided this session (2026-07-16), per the user's direction:** skip Q2 (new photoreal
checkpoint models) for now — optimize the existing pipeline first so the system is
ready when new models land, rather than adding models on top of an unfinished
enhancement layer. Q3 goes next. §3.1's routing design and §3.3's preset taxonomy below
were fleshed out from a dedicated research pass this session (SDXL/FLUX prompt
structure, real-world enhancer system-prompt patterns, preset taxonomy conventions,
rule-vs-LLM routing literature) — see §3.1.5 for sources.

---

## Q3.1 — LLM prompt enhancer

**Mechanics (the Groq→Gemini→raw fallback chain, vision-aware img2img path, multimodal
plumbing prerequisites) are specified in `workspace/plan/plan_vision_prompt_enhancement.md`
— read that plan for routes/registry/testing details. This section specifies what
THIS session's research adds on top: concrete per-model prompt schemas, real
system-prompt text, and the rule-based-vs-LLM-based selection mechanism.**

**Files:** new `backend/app/core/image_prompting.py`, `routes/generate.py`,
`frontend` composer toggle, tests. (Depends on `plan_vision_prompt_enhancement.md`'s
§3.1 multimodal plumbing + §3.3 `PromptSchema` type landing first.)

### 3.1.1 — Per-model prompt structure (research-backed)

**SDXL** — keyword-scaffold, front-loaded (CLIP effectively stops attending after
~75 tokens, so lead with what matters):

```
[Subject/Persona] → [Camera & Lens] → [Lighting] → [Depth of Field] → [Texture/Detail]
→ [Composition/Background] → [Color]
```

Vocabulary bank (feeds `PromptSchema.vocabulary_hints`):
- **Camera/lens:** "shot on Canon EOS 5D Mark IV, 85mm lens", "Sony A7 III, 50mm f/1.8",
  "100mm macro" (product/detail shots)
- **Lighting** (named setups, not vague adjectives): Rembrandt (triangular cheek
  shadow, dramatic portraits), Butterfly (overhead, glamour/beauty), Split (half-face
  lit, moody), Rim (backlit edge glow), Natural (golden hour / window light / overcast
  softbox)
- **Depth of field:** shallow → "f/1.8, subject in sharp focus, bokeh background"
  (portraits); deep → "f/11, everything in sharp detail" (landscapes/product)
- **Texture:** "skin pores, film grain" (people); material words — silk, denim,
  leather, brushed metal (product/fashion)

**FLUX.1-schnell** — natural-language sentences, no keyword soup, confirmed via BFL's
own docs. Loose template (condensable, not a rigid formula):

```
[SUBJECT], [LOCATION], [STYLE], [CAMERA SETTINGS], [LIGHTING], [COLORS], [EFFECT]
```

FLUX's T5 encoder rewards richer natural prose over keyword lists and **weighs earlier
tokens more heavily** — subject always goes first. No negative prompts (BFL's docs
don't mention them at all — silence, not "supported"; matches Q1.4's existing finding
that FLUX's CFG-0 pipeline call has no `negative_prompt` param). **No official
scene-type differentiation** — FLUX presets vary sentence *content*, not *format*,
unlike SDXL where the whole structure can shift for e.g. product shots.

### 3.1.2 — System-prompt text (concrete, schema-driven)

Adapt this real-world pattern (found in a production Stable-Diffusion GPT — see
§3.1.5 sources) rather than hand-authoring prose from scratch:

```
Your objective is to rewrite the user's image description into a highly detailed,
{FORMAT_INSTRUCTION} prompt optimized for {TARGET_MODEL}.

Cover, in order: Subject (detailed description of the main subject/scene),
Medium ({MEDIUM_HINT}), Style (visual treatment), Lighting (specific setup, not
vague), {DOF_LINE} Color (palette/grading), Composition/Background.

{NEGATIVE_INSTRUCTION}

Preserve the user's original intent and any explicit details they gave — add,
don't replace. Output ONLY the rewritten prompt text, nothing else — no preamble,
no explanation, no quotes.
```

Where `{FORMAT_INSTRUCTION}`/`{DOF_LINE}`/`{NEGATIVE_INSTRUCTION}` are generated from
the target `PromptSchema` fields (`format`, `wants_negative`, `vocabulary_hints`), per
`plan_vision_prompt_enhancement.md` §3.3's rule: **one schema is the single source of
truth; the system prompt is derived from it at call time, never hand-duplicated** (a
hand-written prompt per model pair drifts out of sync with the schema over time — the
schema-driven approach is what production ComfyUI-integration prompt-enhancer projects
converge on too, per §3.1.5).

SDXL schema fills in: `FORMAT_INSTRUCTION="keyword-scaffold (comma-separated phrases,
not full sentences)"`, `MEDIUM_HINT="photography, illustration, or render"`,
`DOF_LINE="Depth of field (shallow/deep, with f-stop),"`,
`NEGATIVE_INSTRUCTION="Also produce a separate negative-prompt list of what to
avoid."`.

FLUX schema fills in: `FORMAT_INSTRUCTION="flowing natural-language sentence (no
comma-separated keyword lists)"`, `MEDIUM_HINT` omitted (folds into Style),
`DOF_LINE` omitted, `NEGATIVE_INSTRUCTION=""` (FLUX gets none).

Keep prompts strictly bounded (e.g. under 150 words for SDXL, under 100 for FLUX) —
production examples cap output length explicitly; an unbounded enhancer prompt risks
truncation past SDXL's ~75-token attention window.

### 3.1.3 — Preset-aware enhancement

The enhancer's system prompt additionally receives whichever preset(s) are active
(style preset + subject-type preset, see §3.3) as extra constraints appended to the
template above — e.g. "Style constraint: cinematic — anamorphic lens, dramatic
lighting, film grain, teal-and-orange grade." The enhancer's job becomes "rewrite this
prompt to the target schema, honoring the active preset's vocabulary," not a
context-free rewrite. This is what lets one enhancer call replace both today's
`STYLE_SUFFIXES` string-concatenation (Q3.3 rebuild) and a from-scratch LLM rewrite in
a single pass, instead of running two separate transformations.

### 3.1.4 — Selection mechanism: rule-based default, LLM-based "extra"

Per the user's explicit direction ("api based decision is better option, but also
defaults should be diff and extra should be api based") and confirmed by the
rule-vs-LLM routing research (§3.1.5): **hybrid, heuristic-first — reuses the exact
shape `core/router.py`'s `classify()` already established for chat, not a new pattern.**

- **Rule-based gate (default, free, ~instant):** a fast deterministic check decides
  whether the raw prompt even needs enhancement before any LLM call happens:
  - Prompt already long/detailed (e.g. `>= ENHANCE_SKIP_WORD_THRESHOLD` words AND
    already contains scaffold-shaped content — camera/lighting/style words present) →
    **skip enhancement**, use as-is. A user who already wrote "85mm portrait, golden
    hour, shallow DOF" doesn't need a rewrite.
  - Prompt short/vague (below threshold, no scaffold words detected) → **needs
    enhancement**, proceed to the LLM call.
  - A middle "ambiguous" band (like `router.py`'s heavy/light split) can defer to a
    cheap one-token LLM check the same way `classify()`'s fallback tier does, if the
    simple length/keyword heuristic proves too coarse in practice — start without this,
    add only if the plain heuristic misfires often (avoid speculative complexity).
- **LLM-based enhancement itself is the "extra" tier** — only runs when the rule-based
  gate above says it's needed (or the user forces it on). This keeps the common case
  (already-detailed prompts) at zero LLM latency/cost, and reserves the ~500-2000ms
  LLM round-trip for prompts that actually benefit.
- **User override, always available:** the existing "✨ Enhance" composer toggle
  (Q3.1's original spec) becomes a **3-state control**, not a binary: `Auto` (the
  rule-based gate above decides — default), `Always` (force the LLM call regardless of
  the heuristic), `Off` (never enhance, raw prompt only). Auto is the default so most
  users never think about it; power users who know they want the LLM pass every time
  (or never) can pin it.
- **Never an "AI agent decides autonomously without a rule" mode** — that's strictly
  worse than the hybrid above (pure LLM-decides-whether-to-call-itself is circular and
  adds a second LLM round-trip just to decide on the first one). The rule-based gate
  IS the fast decision layer; the LLM is reserved for the enhancement work itself, not
  for deciding whether to do the enhancement work.

New constants: `ENHANCE_SKIP_WORD_THRESHOLD` (starting guess: 25 words — tune against
the Q1.5 benchmark set once built), a small `_looks_already_scaffolded(prompt) ->
bool` heuristic (regex/keyword check for camera/lighting/lens vocabulary already
present), both in `image_prompting.py`.

### 3.1.5 — Sources (this session's research pass)

- SDXL prompt structure/vocabulary: [Civitai SDXL guide](https://civitai.com/articles/11432/ultimate-guide-to-creating-realistic-sdxl-prompts),
  [Stable Diffusion Art: common problems](https://stable-diffusion-art.com/common-problems-in-ai-images-and-how-to-fix-them/)
- Multi-person SDXL limitations: [Hakky Handbook: multi-person](https://book.st-hakky.com/en/data-science/stable-diffusion-multiple-poses-prompts)
- FLUX prompting: [BFL prompting basics](https://docs.bfl.ml/guides/prompting_unified_basics),
  [Skywork FLUX guide](https://skywork.ai/blog/flux-prompting-ultimate-guide-flux1-dev-schnell/)
- Enhancer system-prompt pattern: [BlackFriday SD prompt enhancer](https://github.com/friuns2/BlackFriday-GPTs-Prompts/blob/main/gpts/stable-diffusion-prompt-enhancer.md),
  [EricRollei/Local_LLM_Prompt_Enhancer](https://github.com/EricRollei/Local_LLM_Prompt_Enhancer),
  [pinkpixel-dev/comfyui-llm-prompt-enhancer](https://github.com/pinkpixel-dev/comfyui-llm-prompt-enhancer)
- Rule-vs-LLM routing: [A Short Primer on LLM Routing](https://kleiber.me/blog/2025/08/10/llm-router-primer/),
  [Google Cloud: Developer's Guide to Model Routing](https://medium.com/google-cloud/a-developers-guide-to-model-routing-1f21ecc34d60),
  [LLM-Based Prompt Routing overview](https://www.emergentmind.com/topics/llm-based-prompt-routing)

**Tests:** per-model scaffold selection, rule-based gate (long/scaffolded prompt skips
LLM call; short/vague prompt triggers it; each of the 3 toggle states), compose order
with presets, LLM-failure fallthrough, both-prompts-stored.

## Q3.2 — Default negatives (SDXL-family)

**Files:** `image_models.py` rows (`default_negative` field), `routes/generate.py` (merge
logic: default + user negative concatenated unless user opts out), UI hint, tests.

- Ship the research-confirmed default (current as of this session's research pass):
  `cartoon, illustration, anime, painting, CGI, 3D render, unrealistic proportions,
  extra fingers, low quality, deformed, extra limbs, bad anatomy, blurry, watermark,
  text` (tuned per row — Juggernaut/RealVis guides have their own recommendations; put
  those on their rows if/when Q2 happens).
- **Multi-person subject-type preset (§3.3) gets an extended negative list** on top of
  the base default — per the multi-person research finding (§3.1.5), blended
  faces/wrong limb counts are a real, only-partially-prompt-fixable SDXL failure mode:
  append `cloned face, fused fingers, too many fingers, malformed limbs, missing arms,
  missing legs, extra arms, extra legs, mutated hands, long neck` when the multi-person
  preset is active.
- FLUX rows: `default_negative = None` + field hidden (Q1.4, already shipped).

**Tests:** merge logic matrix (default only / user only / both / opt-out), multi-person
extended-negative-list activation.

## Q3.3 — Style + subject-type presets (imageLab's mini preset registry)

**Files:** `data/registry/image_presets.json` (new), `routes/generate.py` (replace the
hardcoded `STYLE_SUFFIXES` dict with registry load; keep old keys working), composer
chips UI, tests.

**Two orthogonal preset axes, combinable** (this session's research found no single
authoritative external taxonomy to cite, but the pattern is the natural fit given how
the vocabulary above already splits — lighting/camera choices vary by *subject type*,
medium/color-grade choices vary by *style*, independently):

- **Style axis** (visual treatment — PAWN already has these 5, keep as-is):
  photorealistic, cinematic, anime, oil painting, sketch. Q3 adds: analog film,
  studio product, golden hour, editorial (from `01_research_quality.md`'s original
  list) — 9 total, calibrated against the Q1.5 benchmark set.
- **Subject-type axis** (new this session, composes with any style preset):
  - **Portrait / single person** — the existing default assumption, vocabulary as in
    §3.1.1.
  - **Multi-person / group** — explicit count + plural noun instruction baked into the
    preset ("exactly N people" not "some people"), a distinguishing-trait prompt (hair/
    clothing/expression per person) injected by the enhancer, and §Q3.2's extended
    negative list auto-applied. **Ship with an honest UI caveat** ("multi-person scenes
    are harder for this model — results may blend faces or limbs; consider generating
    people separately and compositing" or similar) — per the research, this is an
    architectural SDXL limitation that prompt phrasing mitigates but doesn't fix; a
    real fix needs regional conditioning (ControlNet pose / Latent Couple) that's out
    of scope for this plan.
  - **Nature / landscape** — deep-DOF vocabulary, no person-specific negatives, sky/
    terrain/weather vocabulary hints.
  - **Product / object** — macro/studio-lighting vocabulary, deep DOF, clean-background
    bias.
  - **Architecture** — wide-angle/perspective vocabulary, golden-hour-or-blue-hour
    lighting bias.
  - Each subject-type preset is per-model-schema-aware (§3.1.1) — the SAME preset
    selection produces keyword-scaffold vocabulary injection for SDXL and
    natural-language sentence content for FLUX, via the shared `PromptSchema`.
- Per-preset optional negative additions and per-model overrides (a preset can carry
  FLUX-phrasing + SDXL-phrasing variants) — same mechanism the original Q3.3 spec had,
  now generalized across both axes instead of just the style axis.

**Tests:** registry schema validation, per-model variant selection, legacy key
compatibility, style×subject-type combination produces correctly merged vocabulary,
multi-person preset applies its extended negative list + UI caveat.

## Q3.4 — Optional: negative embeddings (decision + spike)

- Textual-inversion negatives (unaesthetic/negative-XL family) via
  `pipe.load_textual_inversion` — cheap boost but adds weights hosting + notebook change.
  Run as a SPIKE on one embedding: A/B on the benchmark set; adopt only on a clear win
  (record verdict here). If adopted: embeddings ride the model's weights dataset, one
  notebook line, `default_negative` references the trigger token.

---

## Risks

| Risk | Mitigation |
|---|---|
| Enhancer changes user intent | editable-before-submit UI + toggle + original stored |
| LLM latency on every gen | rule-based gate (§3.1.4) keeps most gens at zero LLM cost; `Always` toggle opts in explicitly |
| Preset/negative soup degrades FLUX | per-model variants; FLUX gets natural-language phrasing only, no negatives ever |
| Multi-person preset overpromises a fix that doesn't exist | explicit UI caveat (§Q3.3); documented as prompt-level mitigation, not a real fix |
| Schema/system-prompt drift (hand-written prompt diverges from schema) | system prompt is generated FROM the schema at call time (§3.1.2), never hand-duplicated |
