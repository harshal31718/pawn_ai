---
name: registry-refresh
description: >
  Refreshes PAWN's model registry (backend/data/registry/models.json and
  endpoints.json) against each free-tier provider's FULL current model catalog
  (not just a diff against what's already registered), and re-derives
  fast/balanced/research tiers from an actual public benchmark leaderboard
  (LMArena / Artificial Analysis) rather than a naming heuristic. Use when the
  user says "refresh models", "update model registry", "check provider
  models", "sync free models", asks to find new/more free models, or reports
  that a provider's model list has changed. Run at least monthly — free-tier
  catalogs and rate limits change without notice.
---

## When This Skill Runs

Triggered by: "refresh models", "update model registry", "refresh the
registry", "check for new free models", "sync provider models", "find more
models we can use", or a report that a model was deprecated / a new free
model launched. Also run this proactively **at least once a month** even
absent a trigger — free-tier catalogs rotate (OpenRouter's `:free` list in
particular can change entirely between runs) and providers deprecate models
without emailing anyone.

## Why the previous version of this skill under-delivered (2026-07-15 rewrite)

A live run found PAWN was missing several real, useful free-tier models
(Llama 3.1 8B Instant, GPT-OSS 20B, Llama 4 Scout — vision-capable, Gemma 4
31B — vision-capable, Gemini 2.5 Pro) and had **3 silent production bugs**:
Groq's `deepseek-r1-distill-llama-70b` had been fully decommissioned months
earlier while PAWN's endpoint stayed `active: true`; Cerebras had deprecated
`llama-3.3-70b` and `qwen-3-32b` on that specific provider; and two
OpenRouter `:free` models PAWN relied on had rotated out of the free tier
entirely. None of this was caught by the old diff-only-against-known-models
approach, and the old capability-level rule (`fast` = small/"lite"-named,
`balanced` = mid, `research` = reasoning-named) was a size/naming guess, not
grounded in anything measured. Both gaps are fixed by the workflow below.

## Purpose

PAWN routes chat through free-tier providers whose available models and rate
limits change over time. This skill re-derives the registry from each
provider's **full** authoritative catalog — not a diff against what's
already there — and buckets capability levels from real benchmark data. It
updates two data files — **data, not code**: no Python changes are part of
this skill (the one exception, `supports_vision` on `ModelEntry` and
`require_vision` on `resolver.pick_model_by_capability`, was a one-time code
addition made 2026-07-15 alongside the first vision-aware refresh — this
skill itself still only ever touches the two JSON files below).

## Files Owned

- `backend/data/registry/models.json` — canonical model entries (schema:
  `id`, `display_name`, `type` chat|reasoning|embedding, `visibility`
  user|internal, `tier`, `capability_level` fast|balanced|research|null,
  `capability_tags`, `context_window`, `active`, `supports_tools`,
  `supports_vision`).
- `backend/data/registry/endpoints.json` — provider endpoints (schema: `id`
  = `ep-<model_id>-<provider>`, `model_id`, `provider`, `provider_model_id`,
  `base_url`, `priority`, `rpm_limit`, `rpd_limit`, `tpm_limit`, `tpd_limit`,
  `active`, `last_verified`).

Read both files FIRST. Preserve schema and field order exactly. The Pydantic
loaders (`backend/app/registry/schemas.py`, `backend/app/registry/loader.py`)
are the contract — if unsure about a field, read the loader, never guess.
Registry iteration order for internal role-level resolution
(`pick_model_by_capability`) is **file order** (Python dict built from the
JSON array preserves insertion order) — deliberately place well-established,
generously-limited models before newly-discovered/lower-confidence ones
within the same capability level, so the resolver prefers the proven option
and only falls through to the new one when needed.

## Authoritative Sources (check in this order per provider)

| Provider | Full model catalog | Rate limits |
|---|---|---|
| google | https://ai.google.dev/gemini-api/docs/models | Google's rate-limits page increasingly just says "check AI Studio" — treat published numbers from third-party aggregators as **unverified** unless corroborated, and say so rather than inventing a number. |
| groq | https://console.groq.com/docs/models | https://console.groq.com/docs/rate-limits — also check https://console.groq.com/docs/deprecations for anything recently decommissioned. |
| cerebras | https://inference-docs.cerebras.ai/models/overview | https://inference-docs.cerebras.ai/support/rate-limits — also check https://inference-docs.cerebras.ai/support/deprecation (Cerebras deprecates per-model, not per-provider — a model can be gone from Cerebras specifically while still fine elsewhere). |
| huggingface | `GET https://router.huggingface.co/v1/models` (public) | https://huggingface.co/docs/inference-providers — HF's router proxies to many backend providers (Groq, Cerebras, Novita, Together, Fireworks, DeepInfra, Featherless, etc.); most of those backends are **paid-only through HF** even when the same model is free directly from its own provider. Only add an HF-routed entry when going direct isn't an option and the backend genuinely has a free quota (e.g. Featherless) — otherwise it's a redundant, less-reliable path to a model PAWN can already reach directly. |
| github | https://docs.github.com/en/github-models/reference/models (catalog) + https://docs.github.com/en/github-models (rate-limit tiers table) | If this page 404s or won't load, do NOT fall back to third-party aggregator sites as your only source for a NEW model entry — report the provider as unverified this run rather than registering something you couldn't confirm against GitHub's own docs. |
| openrouter | `GET https://openrouter.ai/api/v1/models` (public, no key) — filter to `id` ending `:free` or zero pricing | https://openrouter.ai/docs/api-reference/limits (global cap: 20 RPM, 50 RPD with no lifetime purchased credits / 1000 RPD with ≥$10 lifetime purchased credits — applies across ALL `:free` models combined, not per-model) |

Rules for sourcing:
- Prefer the public list APIs (openrouter, huggingface) — exact
  `provider_model_id`s, no scraping ambiguity. Use docs pages for the rest
  and for all rate limits.
- **Fetch each provider's list TWICE independently (or via two different
  phrasings/sources) before trusting a surprising result** — e.g. an
  unfamiliar or much-shorter-than-expected catalog. OpenRouter's `:free`
  list in particular churns hard between runs; don't assume last month's
  list is still valid, and don't assume this month's surprising list is
  wrong either — corroborate, then trust it.
- If a page is unreachable, web-search for the provider's current models
  page — do NOT skip the provider silently, and do NOT register a new model
  sourced only from an uncorroborated third party — report it as
  unverified instead.
- NEVER call authenticated provider APIs by embedding key material in
  commands that echo it. Local `secrets/*` files may be stale (BYOK
  migration made them unused) — do not rely on them; the public sources
  above are sufficient.

## Workflow

1. **Read** both registry files; note every `active: true` entry and its
   `last_verified` date.
2. **Enumerate each provider's FULL current catalog** — not just a check on
   already-registered models. For each provider, ask: "what is every
   text/chat-capable free-tier model this provider serves right now?" and
   list all of them, including ones PAWN has never had. Collect: exact
   provider-side model IDs, context windows, free-tier RPM/RPD/TPM/TPD
   limits, tool-calling support, vision/multimodal-input support,
   reasoning/thinking-model status, deprecation notices. Ignore: live/voice/
   audio/realtime/TTS/STT models, image/video-generation models, and
   moderation/classifier-only models (e.g. prompt-injection guards) — none
   of these are chat-completion models.
3. **Get benchmark grounding for capability-level tiering** — fetch current
   rankings from LMArena (https://lmarena.ai/leaderboard or its current
   successor URL) and/or Artificial Analysis
   (https://artificialanalysis.ai/models — Intelligence Index) for every
   model found in step 2 (or its closest matching variant if an exact match
   isn't listed). Frontier-leaderboard-only tools won't have every small
   free model on them — that's expected; use whatever score you can find
   plus size class as a fallback signal, and say when a model couldn't be
   scored directly.
4. **Diff** against the registry:
   - Endpoint's `provider_model_id` no longer served, or the provider's own
     deprecation page lists it → mark that endpoint `active: false`. **Never
     delete entries** — deactivation preserves history and referential
     integrity.
   - Model has zero remaining active endpoints → keep the model entry but
     verify its `active` flag matches (model-level `active: false` once no
     endpoint is left).
   - New free model on a supported provider (from step 2's full-catalog
     pass, not just from a user report) → propose a new model entry (or a
     new endpoint on an existing model if it's the same model served by
     another provider — match by family+size, e.g. llama-3.3-70b across
     groq/cerebras/huggingface).
   - Rate limits changed → update the endpoint's limit fields.
   - Everything verified → bump `last_verified` to today (YYYY-MM-DD).
5. **Assign fields for new models, grounded in step 3's benchmark data —
   this replaces any purely size/name-based guess:**
   - `capability_level`: bucket using the benchmark score/size class you
     found. A workable starting rule (recalibrate if the score landscape
     shifts): a model whose primary mode is extended reasoning/"thinking"
     → `research`, regardless of raw score (the depth/latency tradeoff is
     the defining trait, not the number). Otherwise: low-end scores or
     explicitly small/"lite"/"mini"-branded → `fast`; mid-range scores →
     `balanced`; only genuinely top-scoring or clearly research-grade,
     large models → `research`. When no benchmark data exists for a model at
     all (common for very new/obscure free entries), say so explicitly and
     make the most defensible size/family-based call, flagged as
     lower-confidence in the report — don't silently treat a guess as
     verified.
   - `capability_tags`: subset of {general, summarization,
     instruction-following, coding, reasoning, math, research}; `vision` is
     an acceptable additional free-form tag for a multimodal model (the
     schema doesn't constrain `capability_tags` to an enum).
   - `supports_vision`: `true` only when the provider's own docs (or a
     corroborated second source) confirm image/multimodal input — this
     directly gates `resolver.pick_model_by_capability(require_vision=True)`,
     used by PAWN's vision-grounded prompt enhancer
     (`plan_vision_prompt_enhancement.md`), so a wrong `true` here is a
     functional bug, not just a label.
   - `priority` on endpoints: order by generosity of free limits (most
     generous = 1), matching the pattern in existing entries.
   - Registry array position: append genuinely new/lower-confidence models
     (obscure free-tier entries with no benchmark corroboration, preview-
     status models) AFTER established models at the same capability level,
     so internal role-level resolution prefers the proven option first.
   - `visibility`: `user` for chat/reasoning, `internal` for embeddings.
   - `type`: `reasoning` only for explicit reasoning/thinking models, else
     `chat`.
6. **Present the diff to the user BEFORE writing** — a compact table: added
   / deactivated / limit-changed / tier-changed / verified-unchanged, per
   provider, with the source URL (and benchmark citation for tier
   assignments) for each claim. Wait for approval. The user may strike
   lines. (Exception: skip this pause only when the user has explicitly
   pre-approved a full refresh-and-apply in the same request — still report
   everything you did afterward exactly as if they'd approved a presented
   diff.)
7. **Write** the approved changes to both files. Formatting: 2-space indent,
   keep existing key order.
8. **Validate**: run the registry tests —
   `docker compose exec backend pytest tests/test_registry.py
   tests/test_resolver.py` (or `python -m pytest
   backend/tests/test_registry.py backend/tests/test_resolver.py` outside
   Docker), then the full suite once — `docker compose exec backend pytest`.
   JSON must parse and every endpoint's `model_id` must reference an
   existing model. If validation fails, fix before finishing.
9. **Document**: append a dated entry to `workspace/status/dev_log.md`
   summarizing the changes, sources, and benchmark citations used for any
   tier assignment. Do NOT update `current_state.md` for a pure registry
   refresh (it's data maintenance, not a build step).

## Hard Rules

- Data files only — never modify Python/TypeScript in this skill (the
  `supports_vision`/`require_vision` schema+resolver addition was a one-time
  prerequisite made outside this skill on 2026-07-15; this skill does not
  add new fields to the Pydantic models going forward without the user
  explicitly asking for a schema change).
- Never delete a model or endpoint entry; `active: false` is the only
  removal.
- Never invent rate limits or a capability score — a limit or benchmark
  score you couldn't verify stays as-is (or gets flagged lower-confidence
  for a new entry) with its old `last_verified` date, and you say so in the
  report.
- Never register a brand-new model sourced from only an uncorroborated
  third party when the provider's own docs page was unreachable — report it
  as unverified instead and leave it for next run.
- Only OpenAI-compatible chat endpoints belong in the registry (all six
  current providers qualify; a new provider requires a code change in
  `llm_core._detect_provider` and is OUT of this skill's scope — flag it to
  the user instead).
- Embedding model entries (`type: "embedding"`) are load-bearing for
  memory/RAG (`gemini-embedding-2`, vector schema): NEVER deactivate or
  dimension-swap them from this skill — flag any change to the user as
  requiring a plan.
- No user approval, no write, unless the user has explicitly pre-approved a
  full apply-without-pausing run (step 6's exception) — still report fully
  afterward either way.

## Output to User

A short report: providers checked (with dates), full diff applied (added /
deactivated / limit-changed / tier-changed), benchmark sources cited for any
tier assignment, anything unverifiable, test result, and the dev_log entry
written.
