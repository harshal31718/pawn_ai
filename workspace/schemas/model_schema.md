# Model schema

Defined 2026-07-23, in discussion with the user, ahead of implementation.
Companion to `provider_schema.md` — this covers `Model` and how it relates
to `Provider`.

## Relationship to Provider

A model can be served by more than one provider (e.g. `llama-3.3-70b` today
has 7 provider endpoints: groq, cerebras, huggingface, github, openrouter,
nvidia, sambanova). This is a many-to-many relationship via a join record
(today's `Endpoint`, in `data/registry/endpoints.json`):

```
Model (1) ──< Endpoint >── (1) Provider
```

- `Model` holds provider-agnostic facts (capability, context window, quality rank).
- `Provider` holds the external-API identity (see `provider_schema.md`).
- `Endpoint` holds everything specific to ONE (model, provider) pairing: the
  provider's own name for the model (`provider_model_id`, which can differ
  from `model_id`), base URL, priority, rate limits, and `key_source`.

`Endpoint.provider` should be a real foreign key into `Provider.id` once
`providers.json` exists, replacing today's hardcoded Pydantic `Literal` in
`schemas.py`.

## Model schema

```jsonc
{
  "id": "gemini-2.5-flash",
  "display_name": "Gemini 2.5 Flash",
  "tags": ["chat", "general", "summarization", "instruction-following", "coding", "vision"],
  "visibility": "user",              // user | internal
  "tier": "free",
  "capability_level": "balanced",    // fast | balanced | research | none
  "context_window": 1048576,
  "active": true,
  "supports_tools": true,
  "supports_vision": true,
  "quality_rank": 10
}
```

```jsonc
// embedding model example
{
  "id": "gemini-embedding-2",
  "display_name": "Gemini Embedding 2",
  "tags": ["embedding"],
  "visibility": "internal",
  "tier": "free",
  "capability_level": "none",
  "context_window": 8192,
  "active": true,
  "supports_tools": true,
  "supports_vision": false,
  "quality_rank": 999
}
```

## What changed from today's `models.json`

- **`type` + `capability_tags` merged into one `tags` list.** `type`'s three
  values (`chat`, `embedding`, `reasoning`) become just more tags alongside
  the existing capability tags (`general`, `coding`, `vision`, `math`,
  `reasoning`, `research`, `summarization`, `instruction-following`) — they
  already overlapped conceptually (e.g. `deepseek-r1` was `type: reasoning`
  AND carried a `"reasoning"` tag). Embedding models, which had an empty
  `capability_tags: []` before, now just get `tags: ["embedding"]`.
- **`capability_level: "none"` is reserved for models that never go through
  capability-level routing at all** — today that's only the embedding
  models (picked directly by id via `pick_model_by_capability`'s bypass,
  never through the `fast`/`balanced`/`research` selection). Internal
  (`visibility: internal`) chat/reasoning models used by the
  orchestrator/subagents are NOT `"none"` — they ARE capability-routed
  (`ROLE_LEVELS` assigns them a real level), just not user-selectable in the
  model switcher. `"none"` is not a general internal/orchestrator catch-all.
- **`tier` kept as-is** (only value today is `"free"` — left in place for
  when a paid-tier model appears, not actively discriminating yet).
- **`quality_rank`/`capability_level`/`tags` stay routing-internal** — this
  schema pass is only about the `Model`↔`Provider` relationship shape and
  the `type`/`capability_tags` merge, not a re-litigation of C1-C5's routing
  design.

## Open implementation questions (not yet decided)

1. Whether `Endpoint` gets renamed now that `Provider` is formalized, or
   keeps its current name (already well-understood in the code as-is).
2. Migration path for existing `models.json`/`endpoints.json` data and every
   call site reading `type`/`capability_tags` today (`router.py`,
   `resolver.py`, `registry/schemas.py`, seed fixtures, tests) — one bulk
   pass vs. incremental.
