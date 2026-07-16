# Phase F-6 — Groq API as Default Orchestrator

**Status:** PLANNED. **Branch:** `dev`. **Folder:** `workspace/plan/chat/`
**Date:** 2026-07-15

## 1. Why this plan exists

Groq endpoints (like Llama 3.3 70B via Groq) have large rate limits and extremely fast token generation speeds. If the user configures their own Groq API key in BYOK Settings, we want PAWN to default to using Groq-backed models/endpoints for the main orchestrator (which runs the planning, agent loop, and subagent orchestration) rather than defaulting to other providers.

## 2. Proposed Changes

**Verified against current code (2026-07-15 refinement pass) — this narrows the original
plan to a smaller, safer diff:**

- `ModelEntry` (`backend/app/registry/schemas.py:19`) already carries a `provider` field
  directly (`Literal["google", "cerebras", "groq", ...]`) — no need to walk endpoints to
  find the provider, `model.provider == "groq"` is enough.
- `pick_model_by_capability` (`resolver.py:106`) is the one actually used by every
  internal caller that matters here: `router.py:94` (orchestrator), `graph.py:228/334`
  (execute-loop tool-calling model), `graph.py:717` (final synthesis), and
  `subagents.py` (via `ROLE_LEVELS`). It iterates `matching` (models at that capability
  level) in registry-file order and returns the first one with a usable endpoint — order
  is currently just `data/registry/models.json`'s insertion order.
- `pick_by_capability` (list-returning, plural) has **no real production caller** —
  every reference outside `resolver.py`'s own definition is a `DummyResolver`/test-double
  stub (e.g. `graph.py:56`, `memory/summarize.py:20`), not a live code path. **Drop it
  from scope** — touching it adds risk/diff for a method nothing calls.
- `key_store.get_key(user_id, "groq")` (existing function, `key_store.py:96`) is the
  right check — returns `None` if no Groq key is configured. No new helper needed
  (`has_search_key` is search-provider-specific, not reusable here).

#### [MODIFY] [resolver.py](file:///c:/Users/harsh/Desktop/PAWN/backend/app/resolver/resolver.py)
- In `pick_model_by_capability` only: before the `for model in matching:` loop
  (`resolver.py:125`), if `user_id is not None and key_store.get_key(user_id, "groq")`,
  stable-sort `matching` so entries with `model.provider == "groq"` come first,
  preserving relative order otherwise. The existing loop (checks `require_tools`, then
  `_has_usable_endpoint`) is untouched — if the prioritized Groq model has no usable
  endpoint (rate-limited/cooled down/no active endpoint), the loop already falls through
  to the next matching model exactly as today. This keeps the fallback guarantee free —
  no new code needed for it.
- No changes needed to `constants.py` — `ROLE_LEVELS` already maps role → capability
  level; this change is orthogonal (it re-orders *within* a level, doesn't touch which
  level a role uses).

## 3. Verification Plan

### Automated Tests
- Extend `backend/tests/test_resolver.py` (or registry/resolver unit tests) to mock keys for both `google` and `groq`.
- Verify that `pick_model_by_capability` prioritizes the Groq model if the user holds a Groq key.
- Verify that if the Groq key is absent, the resolver falls back to the default Gemini model.

### Manual Verification
- Add a Groq API key in the UI Settings under "Bring Your Own Key".
- Start a chat that triggers the agent (e.g., ask a heavy question).
- Check the trace log/steps to verify that the orchestrator operations are routed `via Groq`.

### Scope note
This also changes final-synthesis and subagent model choice (they all route through
`pick_model_by_capability`), not just the orchestrator step — call this out to the user
before building, since "default orchestrator" in the title is narrower than the actual
effect. If the user only wants the plan/execute-loop model affected, `pick_model_by_capability`
would need a `prefer_provider` param instead of a global change — worth a quick confirm.

## 4. DONE (2026-07-16)

**Plan premise corrected during implementation:** §2 assumed `ModelEntry`
already carries a `provider` field directly (`model.provider == "groq"`).
That's factually wrong against current code — `provider` only exists on
`EndpointEntry`; one `ModelEntry` can span several providers via its
endpoints (e.g. `llama-3.3-70b` has cerebras/github/groq/huggingface/
openrouter endpoints under one model). Implemented instead as:

- New `Resolver._has_groq_endpoint(model_id)` — True if any of the model's
  active endpoints (`registry.endpoints_for()` already filters to active)
  are on Groq.
- In `pick_model_by_capability`, right after computing `matching`: if the
  user holds a Groq key, `matching = sorted(matching, key=lambda m: not
  self._has_groq_endpoint(m.id))` — a stable sort promoting Groq-endpoint-
  having models first, otherwise preserving file order. The existing
  per-model `require_tools`/`require_vision`/`_has_usable_endpoint` loop is
  completely untouched, so the fallback-to-next-model guarantee (rate-
  limited/cooled-down/keyless Groq endpoint) still holds for free.
- `pick_by_capability` (plural, no real production caller) left untouched
  per the plan's own scope note.

3 new tests in `test_resolver.py` (later trimmed to 2 after code-reviewer
flagged one as a no-op that would pass even with the reorder logic
deleted — removed rather than kept as a misleading regression guard).
Full backend suite green (445, `docker compose exec backend pytest -n auto`
— required the now-familiar `docker compose build backend` + container
recreate since `backend/tests/` isn't bind-mounted). code-reviewer PASS
(1 WARN fixed — the no-op test, above; 1 NOTE fixed — `_has_groq_endpoint`'s
docstring corrected to acknowledge `endpoints_for()` already filters to
active endpoints).

**Scope confirmed as originally noted:** this does affect final-synthesis
and subagent model choice too, not just the plan/execute-loop step — all of
them route through `pick_model_by_capability`, and no narrower
`prefer_provider` param was requested, so the global reorder stands.

**Manual live verification still needs the user** — adding a real Groq API
key in Settings is something this session must not do itself (entering API
keys/credentials is a prohibited action regardless of context per this
project's standing safety rules). Automated tests + code review are the
verification for this step; the user can confirm live by adding their own
Groq key and checking the trace's "via Groq" tag on a heavy/agentic turn.
