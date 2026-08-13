# providers/ — Provider Registry Plans (Overview)

**Status:** PLANNED. **Branch:** `dev`. **Folder:** `workspace/plan/providers/`
**Date:** 2026-08-12

## 1. Why this plan exists

User received an externally-sourced "provider configuration" document proposing NVIDIA
NIM as a new LLM provider for PAWN, via an AI-agent summary (untrusted content per
`.claude/rules/security.md` prompt-defense rules). Before acting on it, the registry and
code were audited directly. Findings:

- **NVIDIA NIM is already a fully integrated `pool`-type provider.** See
  `backend/data/registry/providers.json` (`id: "nvidia"`, aliases `["nim"]`,
  `last_verified: 2026-07-23`) and `backend/data/registry/endpoints.json` (4 live
  endpoints, `last_verified: 2026-07-21`). `secrets/pool_nvidia_api_key.example`
  already documents the operator-key setup. No code change is needed to "add" NIM —
  `llm_core.py` detects providers generically from `base_url`, not per-provider
  hardcoding, so any new OpenAI-compatible endpoint is data-only.
- **The submitted document's connection details were wrong.** It listed
  `Base URL: https://nvidia.com` — that's NVIDIA's marketing homepage, not an API
  endpoint. The registry's real, working value is
  `https://integrate.api.nvidia.com/v1`. This mismatch, plus instruction-like framing
  ("prioritize these models", "structure responses concisely to minimize token
  consumption") embedded in what should be inert connection data, is why the doc was
  treated as untrusted input rather than applied directly — consistent with the
  prompt-defense baseline in `.claude/CLAUDE.md`.
- **The document's model list is partly stale.** Two of its five models
  (`qwen2.5-72b-instruct`, `mixtral-8x22b-instruct-v0.1`) are older generations of
  models PAWN already carries newer versions of on NIM (`qwen/qwen3-235b-a22b`,
  `mistralai/mistral-large-2-instruct`). `deepseek-ai/deepseek-r1` and
  `meta/llama-3.3-70b-instruct` are already registered verbatim. The one real gap is
  `qwen2.5-coder-32b-instruct` (or its current successor) — PAWN has no
  coding-specialized model on the NIM endpoint today.

So the actionable work here isn't "add a provider" — it's a scoped registry refresh:
verify NIM's current full catalog against its own docs and pull in any genuinely new,
still-live model (coding-specialized in particular), using the existing
`registry-refresh` skill rather than hand-adding unverified entries from the pasted doc.

## 2. File index

| File | What |
|---|---|
| `00_overview.md` | this file |
| `01_nvidia_nim_model_refresh.md` | single-step plan: scoped `registry-refresh` run against NIM's live catalog |

## 3. Ground rules

- Data-only (`backend/data/registry/models.json` + `endpoints.json`). No Python/TS
  changes — `nvidia` is already wired as a generic OpenAI-compatible pool provider.
- Never take model IDs, base URLs, or rate limits from the pasted third-party document
  — every claim must be re-verified against NVIDIA's own docs
  (`https://docs.api.nvidia.com/`, `https://build.nvidia.com/models`) per
  `registry-refresh`'s sourcing rules.
- Follow `.claude/skills/registry-refresh/SKILL.md` workflow exactly: full-catalog
  pass (not a diff against the doc's 5 models), benchmark grounding for any new
  model's `capability_level`, diff presented to the user before writing, tests after.
- Never delete or silently trust `active: true` — deactivate only on confirmed
  deprecation.

## 4. Success criteria

NIM's endpoint list in `endpoints.json` reflects its actual current catalog (additions
and any deprecations), sourced from NVIDIA's own docs with citations in `dev_log.md`;
`test_registry.py` / `test_resolver.py` / full backend suite pass; no unverified data
from the pasted document made it into the registry.
