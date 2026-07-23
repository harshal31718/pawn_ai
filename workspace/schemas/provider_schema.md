# Provider schema

Defined 2026-07-23, in discussion with the user, ahead of implementation.

## Definition

A **provider** is any external object whose API PAWN sends requests to —
covers LLM chat/image providers, search providers (Tavily, Brave), and
Kaggle. Anything PAWN needs a credential to talk to is a provider.

## Schema

```jsonc
{
  "id": "google",                    // stable slug, primary key — used everywhere in code
  "name": "Google (Gemini)",         // human display name
  "official_docs_link": "https://ai.google.dev/",
  "signup_link": "https://aistudio.google.com/apikey",   // where a user gets a key
  "auth_type": "bearer_key",         // bearer_key | oauth | none
  "capabilities": ["chat"],          // chat | image | internet | kaggle (list — a provider may span more than one)
  "aliases": ["gemini"],             // alternate names that resolve to this id
  "type": "pool"                     // byok | pool
}
```

## Field notes

- **`id` vs `name`**: `id` is a stable slug never used for display; `name` is
  the human-facing label and can change independently.
- **`auth_type`**: describes HOW auth works for this provider, not a stored
  credential. Real key values are per-user (`user_api_keys`) or per-pool
  (`pool_api_keys`) secrets, never stored in this registry.
- **`capabilities`**: a list, not a single value — `internet` (Tavily,
  Brave) and `kaggle` have no models at all (see below); `chat`/`image`
  providers derive their model list from `data/registry/endpoints.json`
  (provider → model relationship), never duplicated here.
- **`aliases`**: absorbs today's `resolver.PROVIDER_ALIASES` (e.g.
  `"gemini"` → `"google"`, `"nim"` → `"nvidia"`, `"glm"` → `"zhipu"`).
- **`type`**: `"pool"` means the operator may (optionally) share their own
  key for this provider as a fallback for keyless users, subject to
  `quota_share`'s fair-division. `"byok"` means bring-your-own-key only — no
  pool sharing exists for it. This is a mechanism distinction, not a
  cost/pricing one: whether a BYOK provider is free or paid is the user's
  own concern, not tracked here. Today `"pool"` only applies to the 11 LLM
  providers (the only ones wired into the resolver/quota-share machinery);
  `internet`/`kaggle` providers are always `"byok"`.

## What this replaces

One registry (`data/registry/providers.json`, to be created) becomes the
single source of truth for what today is duplicated/hardcoded across:

- `backend/app/core/key_store.VALID_PROVIDERS`
- `backend/app/core/pool_key_store.POOL_VALID_PROVIDERS`
- `backend/app/resolver/resolver.PROVIDER_ALIASES`
- `backend/app/registry/schemas.EndpointEntry.provider` (Pydantic `Literal`)
- Frontend `ApiKeysSection.tsx`'s `PROVIDERS`/`MORE_PROVIDERS`/`SEARCH_PROVIDERS` arrays
- Duplicated `formatProviderName()` string-mapping functions (ProvidersPage.tsx, Message.tsx, ModelSwitcher.tsx)

## Open implementation questions (not yet decided)

1. Data file (`data/registry/providers.json`, editable without a deploy,
   matching `models.json`/`endpoints.json`'s existing convention) vs a
   Python module constant.
2. Migration path for the ~6 existing call sites above — replace in place,
   one at a time, with tests, or a single larger pass.
