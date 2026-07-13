---
name: registry-refresh
description: >
  Refreshes PAWN's model registry (backend/data/registry/models.json and
  endpoints.json) against each free-tier provider's current documentation and
  public model-list APIs. Use when the user says "refresh models", "update model
  registry", "check provider models", "sync free models", or reports that a
  provider's model list has changed.
---

## When This Skill Runs

Triggered by: "refresh models", "update model registry", "refresh the registry",
"check for new free models", "sync provider models", or a report that a model was
deprecated / a new free model launched.

## Purpose

PAWN routes chat through free-tier providers whose available models and rate limits
change over time. This skill re-verifies the registry against each provider's
authoritative source and updates the two data files — **data, not code**: no Python
changes are ever part of this skill.

## Files Owned

- `backend/data/registry/models.json` — canonical model entries (schema: `id`,
  `display_name`, `type` chat|reasoning|embedding, `visibility` user|internal,
  `tier`, `capability_level` fast|balanced|research|null, `capability_tags`,
  `context_window`, `active`; plus `supports_tools` once Phase A ships).
- `backend/data/registry/endpoints.json` — provider endpoints (schema: `id`
  = `ep-<model_id>-<provider>`, `model_id`, `provider`, `provider_model_id`,
  `base_url`, `secret`, `priority`, `rpm_limit`, `rpd_limit`, `tpm_limit`,
  `tpd_limit`, `active`, `last_verified`).

Read both files FIRST. Preserve schema and field order exactly. The Pydantic
loaders (`backend/app/registry/loader.py`) are the contract — if unsure about a
field, read the loader, never guess.

## Authoritative Sources (check in this order per provider)

| Provider | Model list | Rate limits |
|---|---|---|
| google | https://ai.google.dev/gemini-api/docs/models | https://ai.google.dev/gemini-api/docs/rate-limits (free tier table) |
| groq | https://console.groq.com/docs/models | https://console.groq.com/docs/rate-limits |
| cerebras | https://inference-docs.cerebras.ai/ (models page) | same docs, free-tier section |
| huggingface | `GET https://router.huggingface.co/v1/models` (public) | https://huggingface.co/docs/inference-providers |
| github | https://docs.github.com/en/github-models + https://github.com/marketplace/models | https://docs.github.com/en/github-models (rate-limit tiers table) |
| openrouter | `GET https://openrouter.ai/api/v1/models` (public, no key) — free models have `:free` id suffix / zero pricing | https://openrouter.ai/docs (free-tier limits) |

Rules for sourcing:
- Prefer the public list APIs (openrouter, huggingface) — exact
  `provider_model_id`s, no scraping ambiguity. Use docs pages for the rest and for
  all rate limits.
- If a page is unreachable, web-search for the provider's current models page —
  do NOT skip the provider silently; report it as unverified.
- NEVER call authenticated provider APIs by embedding key material in commands
  that echo it. Local `secrets/*` files may be stale (BYOK migration made them
  unused) — do not rely on them; the public sources above are sufficient.

## Workflow

1. **Read** both registry files; note every `active: true` entry and its
   `last_verified` date.
2. **Fetch** each provider's sources above. Collect: currently available
   free-tier chat/reasoning models, exact provider-side model IDs, context
   windows, free-tier RPM/RPD/TPM/TPD limits, deprecation notices.
3. **Diff** against the registry:
   - Endpoint's `provider_model_id` no longer served → mark that endpoint
     `active: false`. **Never delete entries** — deactivation preserves history
     and referential integrity.
   - Model has zero remaining active endpoints → mark the model `active: false`.
   - New free model on a supported provider → propose a new model entry (or a new
     endpoint on an existing model if it's the same model served by another
     provider — match by family+size, e.g. llama-3.3-70b across groq/cerebras).
   - Rate limits changed → update the endpoint's limit fields.
   - Everything verified → bump `last_verified` to today (YYYY-MM-DD).
4. **Assign fields for new models** (do not improvise beyond this):
   - `capability_level`: `fast` = small/lite models (≤~10B or "lite"/"mini"
     naming); `balanced` = mid/large instruct models; `research` = reasoning
     models (R1-class, o-class, "thinking" variants). `type`: `reasoning` only
     for explicit reasoning models, else `chat`.
   - `capability_tags`: subset of {general, summarization,
     instruction-following, coding, reasoning, math, research}.
   - `priority` on endpoints: order by generosity of free limits (most generous
     = 1), matching the pattern in existing entries.
   - `visibility`: `user` for chat/reasoning, `internal` for embeddings.
   - `secret`: follow existing naming (`<provider>_api_key`; google uses
     `gemini_api_key`).
5. **Present the diff to the user BEFORE writing** — a compact table:
   added / deactivated / limit-changed / verified-unchanged, per provider, with
   the source URL for each claim. Wait for approval. The user may strike lines.
6. **Write** the approved changes to both files. Formatting: 2-space indent,
   keep existing key order.
7. **Validate**: run the registry tests —
   `docker compose exec backend pytest tests/test_registry.py` (or
   `python -m pytest backend/tests/test_registry.py` outside Docker). JSON must
   parse and every endpoint's `model_id` must reference an existing model. If
   validation fails, fix before finishing.
8. **Document**: append a dated entry to `workspace/status/dev_log.md`
   summarizing the changes and sources. Do NOT update `current_state.md` for a
   pure registry refresh (it's data maintenance, not a build step).

## Hard Rules

- Data files only — never modify Python/TypeScript in this skill.
- Never delete a model or endpoint entry; `active: false` is the only removal.
- Never invent rate limits — a limit you couldn't verify stays as-is with its
  old `last_verified` date, and you say so in the report.
- Only OpenAI-compatible chat endpoints belong in the registry (all six current
  providers qualify; a new provider requires a code change in
  `llm_core._detect_provider` and is OUT of this skill's scope — flag it to the
  user instead).
- Embedding model entries (`type: "embedding"`) are load-bearing for memory/RAG
  (`text-embedding-004`, vector(768) schema): NEVER deactivate or dimension-swap
  them from this skill — flag any change to the user as requiring a plan.
- No user approval, no write. Step 5 is not optional.

## Output to User

A short report: providers checked (with dates), diff applied, anything
unverifiable, test result, and the dev_log entry written.
