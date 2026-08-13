# providers/01 — NVIDIA NIM: Coding-Model Gap + Rate-Limit Verification

**Status:** PLANNED — 1 step, not yet started. **Branch:** `dev`. **Skill:** `registry-refresh`
(scoped to `nvidia` only — do not touch other providers in this step).
**Date:** 2026-08-12

## 1. Scope

Both registry files get touched, matching PAWN's schema split:

- `backend/data/registry/models.json` — the model entry (provider-agnostic).
- `backend/data/registry/endpoints.json` — the NIM **pool** endpoint for that model
  (`provider: "nvidia"`, `key_source: "either"`, matching every existing nvidia row).

`providers.json` needs no change — `nvidia` (`type: "pool"`, aliases `["nim"]`) is
already registered there since the prior provider-expansion phase
(`workspace/status/build_tracker.md`, "R1: 5 new OpenAI-compatible free providers").
This step is additive: new model + new endpoint(s), nothing existing is modified except
possibly `last_verified` bumps on the 4 current nvidia endpoints once re-checked.

## 2. Current state (verified against the repo, 2026-08-12)

| model_id | provider_model_id | endpoint id | priority | rpm_limit | last_verified |
|---|---|---|---|---|---|
| qwen-3-235b | `qwen/qwen3-235b-a22b` | ep-qwen-3-235b-nvidia | 1 | 40 | 2026-07-21 |
| deepseek-r1 | `deepseek-ai/deepseek-r1` | ep-deepseek-r1-nvidia | 4 | 40 | 2026-07-21 |
| llama-3.3-70b | `meta/llama-3.3-70b-instruct` | ep-llama-3.3-70b-nvidia | 6 | 40 | 2026-07-21 |
| mistral-large-3 | `mistralai/mistral-large-2-instruct` | ep-mistral-large-3-nvidia | 2 | 40 | 2026-07-21 |

No model in PAWN's registry currently carries the `coding` capability tag on the nvidia
endpoint — `qwen-3-32b` (`capability_tags` includes general/fast use, not coding-tagged)
is the closest, served by other providers, not NIM.

## 3. Findings from this session's web research (sources below)

**Rate limits (free tier / trial):** NVIDIA's own docs describe the trial limit as
"dependent on model, use-case, and current overall traffic," with third-party
corroboration (NVIDIA Developer Forums threads, independent guides) converging on a
practical baseline of **~40 requests/minute** per API key across the catalog, with an
optional application for a **200 RPM** upgrade. This matches the `rpm_limit: 40` already
set on all 4 existing nvidia endpoints — no change needed there, and 40 is the right
default for any new nvidia endpoint added in this step. No published RPD/TPM/TPD cap
was found (consistent with the existing rows, which all carry `null` for those fields)
— do not invent one.

**Coding-model gap, confirmed still live:**
- `qwen/qwen2_5-coder-32b-instruct` — has an NVIDIA docs reference page
  (`docs.api.nvidia.com/nim/reference/qwen-qwen2_5-coder-32b-instruct`) and a live
  `build.nvidia.com` model card. 32K context. This is the model the (untrusted) source
  document named — it does still exist on NIM, unlike its other two stale entries.
- `qwen/qwen3-coder-480b-a35b-instruct` — also live on NIM (docs reference page +
  `build.nvidia.com` model card), purpose-built for **agentic coding**, 262,144-token
  native context (extendable to 1M), 480B total / 35B activated params. This is a newer,
  substantially stronger option than the 2.5-Coder-32B the source doc listed, and NIM
  serves it as a **Free Endpoint**.

**Recommendation:** register `qwen3-coder-480b-a35b-instruct` as the new coding model
rather than the older `qwen2.5-coder-32b-instruct` — same free-endpoint status, larger
context, agentic-coding-tuned, and avoids adding a model that's already one generation
behind what NIM itself is promoting. Flagging both here per `registry-refresh`'s
diff-before-write rule; final pick is the user's call, not silently decided.

## 4. Proposed diff (for approval — nothing written yet)

**`models.json`** — new entry:
```json
{
  "id": "qwen-3-coder-480b",
  "display_name": "Qwen3 Coder 480B A35B",
  "type": "chat",
  "visibility": "user",
  "tier": "free",
  "capability_level": "research",
  "capability_tags": ["coding", "reasoning"],
  "context_window": 262144,
  "active": true,
  "supports_tools": true,
  "supports_vision": false
}
```
`capability_level: research` follows the skill's rule for large, agentic/reasoning-tuned
models rather than a raw size guess — flagged lower-confidence pending an
Artificial Analysis / LMArena score lookup for this specific model in the actual
registry-refresh run (not done here — this file is the plan, not the executed refresh).

**`endpoints.json`** — new entry:
```json
{
  "id": "ep-qwen-3-coder-480b-nvidia",
  "model_id": "qwen-3-coder-480b",
  "provider": "nvidia",
  "provider_model_id": "qwen/qwen3-coder-480b-a35b-instruct",
  "base_url": "https://integrate.api.nvidia.com/v1",
  "priority": 1,
  "rpm_limit": 40,
  "rpd_limit": null,
  "tpm_limit": null,
  "tpd_limit": null,
  "key_source": "either",
  "active": true,
  "last_verified": "2026-08-12"
}
```

## 5. Execution steps (run via the `registry-refresh` skill, scoped to nvidia)

1. Re-fetch NIM's full current catalog from `https://docs.api.nvidia.com/` and
   `https://build.nvidia.com/models` (not just the two coder models above) — confirm
   nothing else new/relevant surfaced, and confirm the 4 existing entries are still
   being served under the same `provider_model_id`s.
2. Get a benchmark cite for `qwen3-coder-480b-a35b-instruct`'s `capability_level`
   (LMArena / Artificial Analysis) before finalizing — replace the "research, flagged"
   placeholder above with a sourced tier.
3. Present the diff table (this file's §4, plus anything new from step 1) to the user;
   wait for approval per `registry-refresh` step 6.
4. Write both JSON files, 2-space indent, existing key order preserved.
5. Run `docker compose exec backend pytest tests/test_registry.py
   tests/test_resolver.py`, then the full backend suite.
6. Append a dated `dev_log.md` entry with sources and the benchmark citation. Do not
   touch `current_state.md` (data-only refresh, not a build step).

## 6. Explicit non-goals

- Not adding `qwen2.5-coder-32b-instruct`, `qwen2.5-72b-instruct`, or
  `mixtral-8x22b-instruct-v0.1` from the original source document as-is — the first is
  superseded by the qwen3-coder recommendation above, the latter two duplicate
  newer models PAWN already carries on this same provider (§1 of `00_overview.md`).
- Not changing `providers.json` — nvidia's provider-level entry is already correct.
- Not touching `llm_core.py` or any other code path — this provider is already
  code-integrated as a generic OpenAI-compatible pool provider.

## Sources

- [NVIDIA NIM API Pricing 2026: Free Tier, 40 RPM & Real Cost](https://decodethefuture.org/en/nvidia-nim-api-pricing-limits-guide/)
- [NVIDIA Build Free API 2026: 100+ NIM Models, 40 RPM, Setup & No Credit Card](https://yangmao.ai/en/providers/nvidia-build/)
- [NVIDIA Build (NIM API) Free Tier, Signup Credits, and Limits](https://yangmao.ai/en/providers/nvidia-build/free-tier/)
- [\[Request\] NVIDIA NIM Free Tier Rate Limit Increase – 40 RPM Severely Limits Agentic AI Workflows — NVIDIA Developer Forums](https://forums.developer.nvidia.com/t/request-nvidia-nim-free-tier-rate-limit-increase-40-rpm-severely-limits-agentic-ai-workflows/369762)
- [Clarity on NIM API Free Tier Rate Limit Increases — NVIDIA Developer Forums](https://forums.developer.nvidia.com/t/clarity-on-nim-api-free-tier-rate-limit-increases/369624)
- [qwen / qwen2.5-coder-32b-instruct — NVIDIA NIM API docs](https://docs.api.nvidia.com/nim/reference/qwen-qwen2_5-coder-32b-instruct)
- [qwen / qwen3-coder-480b-a35b-instruct — NVIDIA NIM API docs](https://docs.api.nvidia.com/nim/reference/qwen-qwen3-coder-480b-a35b-instruct)
- [build.nvidia.com — qwen3-coder-480b-a35b-instruct model card](https://build.nvidia.com/qwen/qwen3-coder-480b-a35b-instruct/modelcard)
