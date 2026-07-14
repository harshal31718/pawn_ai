# Plan: Reply Generation Quality — Synthesis, Task Separation, Model Use

*Branch: dev. Status: decisions locked 2026-07-14, not yet built. Drafted 2026-07-14 (Cowork session).*
*Tracker: register as Phase O in `workspace/status/build_tracker.md`.*
*Depends on / touches: Phase A (`workspace/implemented_phases/phase_12_chat_agent_refinement.md`) and Phase N (`workspace/plan/plan_interleaved_agent_streaming.md`) — this plan modifies `agent/graph.py`'s `execute_node`, `agent/tools/web_search.py`, `agent/subagents.py`, `core/router.py`, and `constants.py`.*

---

## 1. Trigger

A benchmark prompt (elite geopolitical/economic feasibility analysis of a green-hydrogen
export hub, `[Insert Country]` → auto-grounded to India) produced a report an external
evaluator (Gemini) scored **3.5/10**. Failures observed in the output:

- **Hallucinated logistics:** named "Deendayal Port" and "Kandla Port" as two distinct
  deepwater hubs — they are the *same* port (Kandla renamed Deendayal, 2017). Missed
  India's real second hubs (Mundra, V.O. Chidambaranar/Tuticorin, Gopalpur).
- **Ignored an explicit calculation:** the prompt required a transport-distance estimate
  from the best solar/wind region to the ports. Not attempted.
- **Dropped the competitor cross-reference:** planned to track Reliance/Adani, then gave
  generic "high competition from established players" instead of real project tracking.
- **Generic table:** "Regulatory Hurdles" column contained economic factors, not
  regulatory ones; every cell was a low-effort bullet, not mapped data.
- **Stale data:** described the 2023 launch policy, not 2026 operational benchmarks / PLI
  tranches; LCOH given only as a generic "$2–3/kg by 2030".

---

## 2. Root cause — corrected against the evaluator's guess

The evaluator's headline diagnosis ("raw search data was dropped/summarized away during
the `gemini-2.5-flash → llama-3.3-70b` provider switch, so Llama guessed from parametric
memory") is **wrong**, and matters that it's wrong, because it points at the failover
plumbing instead of the real defects.

`execute_node` (`agent/graph.py`) carries one `working_messages` list — including every
`role:"tool"` observation — across the entire loop. `normalize.chat_stream_with_tools`
failover swaps only the *endpoint/model*; it does not truncate or reset `working_messages`.
So the search observations **were** in context when Llama synthesized. Context loss is not
the bug. The real causes, in priority order:

| # | Cause | Evidence | Severity |
|---|---|---|---|
| **RC-1** | **No capability floor on final synthesis.** Phase N (2026-07-14) merged `final_node` into `execute_node`; the old `final_node` synthesized on `ROLE_LEVELS["final_heavy"]="research"` (→ deepseek-r1). Now *every* iteration, including the final answer, runs on `ROLE_LEVELS["orchestrator"]="fast"`, and after two failovers that was `llama-3.3-70b`. The step that most needs reasoning lost its strong model. | `graph.py` docstring: "resolve_final_model … is no longer called from here — every iteration uses the same orchestrator-capable model picked once." `constants.py` ROLE_LEVELS. | **Highest** |
| **RC-2** | **web_search returns snippets only.** `_format_results` emits `title — url — snippet`, ≤5 results (`WEB_SEARCH_MAX_RESULTS=5`), no page-body fetch. The model never sees the text that contains port names, distances, LCOH figures, PLI tranche numbers. | `agent/tools/web_search.py` L27-31, L50-55. | **High** |
| **RC-3** | **Plan is decorative; no verifier.** `plan_node` output is prepended as a system message and never enforced. Graph is `classify → plan → execute → END` — nothing checks the answer against the prompt's explicit constraints, so dropped requirements (distance calc, named competitors, per-source citations) are never caught. | `graph.py` `plan_node`, `build_agent_graph` edges. | **High** |
| **RC-4** | **Decomposition is left to the orchestrator's whim.** Subagents (researcher/summarizer/coder) exist but the `"fast"` orchestrator model *chooses* whether to `delegate_researcher`. On this run it called `web_search` directly and never ran the structured research loop that `fetch_url`s pages. | `agent/subagents.py`; `execute_node` tool-call dispatch. | **Medium** |
| **RC-5** | **No extraction schema.** The researcher subagent's system prompt says "return a concise digest with sources" — no instruction to pull named entities, numbers, or units, and no per-fact source binding. Snippets in, vibes out. | `subagents.py` researcher `system_prompt`. | **Medium** |

**Uncomfortable summary:** most of this is not a model-quality problem, it's an
architecture problem — and RC-1 is a self-inflicted regression from yesterday's merge.
Throwing a bigger model at it without fixing RC-2/RC-3 will still produce a confident,
well-written, under-sourced report.

---

## 3. Design principles (proposed — confirm before build)

1. **Deterministic quality floor, not model roulette.** The user-facing synthesis must run
   on a `research`-tier model with a hard, ordered fallback list; failover may degrade the
   model but must never silently drop below a defined floor without saying so in the trace.
2. **Separate the roles that were collapsed.** Orchestration/tool-driving (fast, tool-capable)
   and final synthesis (research-tier reasoning) are different jobs and should not share one
   model pick, which is exactly what Phase N collapsed. Re-separate them *without* re-breaking
   Phase N's interleaved streaming.
3. **Make the plan a contract, not a caption.** If a step promised a calculation or a named
   competitor, the output is checked for it before the turn ends.
4. **Extraction over snippets.** Research must fetch and extract page bodies for the top hits,
   not synthesize from search-result descriptions.
5. **Cheap where it's cheap.** Keep the `direct_answer` fast path untouched — none of this
   applies to `needs_agent=False` traffic (the majority). All added cost is gated behind
   `difficulty="heavy"`.

---

## 4. Proposed changes (phased)

### O.1 — Restore a capability floor for final synthesis *(fixes RC-1)* — **LOCKED: O.1-a**

**Decision (2026-07-14):** dedicated final synthesis pass (O.1-a). O.1-b (whole heavy loop
on research tier) rejected — slower and burns the strong model on trivial tool-driving.

After the tool loop resolves (no more `tool_calls`, or budget/iteration cap hit), do the
*final* `stream_iteration(use_tools=False)` on a model resolved from
`ROLE_LEVELS["final_heavy"]="research"` (honoring the user's explicit ModelSwitcher pick
first, exactly as the deleted `resolve_final_model` did), not on the orchestrator model.
Mid-loop "thinking" tokens still stream from the fast orchestrator model (Phase N behavior
preserved); only the closing synthesis is upgraded. Cost: one extra model handoff on heavy
turns only — acceptable under the quality-over-speed decision (§7).

Give `final_heavy` an explicit ordered fallback chain and emit a **trace warning** when
synthesis is forced below the research tier by failover, so a degraded answer is visibly
labeled rather than silently generic.

*Files:* `agent/graph.py` (`execute_node` close-out), `core/router.py` (`resolve_final_model`
already exists — re-wire it), `constants.py` (fallback ordering if needed).

### O.2 — Deep research: fetch + extract, not snippets *(fixes RC-2, RC-5)*

- Add an "auto-fetch top-N" step so `web_search` results feed `fetch_url` (already
  SSRF-guarded, `trafilatura` extraction exists) for the top 2–3 hits per query, and the
  extracted body — not the snippet — becomes the observation. Bound by a new
  `WEB_SEARCH_FETCH_TOP_N` constant and the existing token budget.
- Rewrite the researcher subagent `system_prompt` to demand a **structured extraction**:
  named entities, figures **with units**, dates, and a source URL bound to each fact; explicit
  "if a required number is not found, say so — do not estimate."
- Bump `WEB_SEARCH_MAX_RESULTS` (5 → 8, tunable) so heavy research has more to fetch from.

*Files:* `agent/tools/web_search.py`, `agent/tools/fetch_url.py` (reuse), `agent/subagents.py`,
`constants.py`.

### O.3 — Plan-as-contract + verifier node *(fixes RC-3)* — **LOCKED: deep-research only, 1–2 passes**

**Decision (2026-07-14):** include the verifier for **deep-research requirements only** — not
every heavy turn, and never on the light/direct-answer path. Allow **one to two** revision passes
(not a single hard-capped loop).

Add a `verify` node between `execute` and `END`, gated to deep-research turns (define the trigger:
`difficulty="heavy"` AND the turn actually used research tools / delegated to `researcher`, so a
heavy-but-non-research turn like a long code task doesn't pay for it). It runs one `research`-tier
check: given the original user request + the plan + the drafted answer, does the answer satisfy
each explicit, checkable constraint (required calculations performed? named entities present? every
data point cited?). On failure it returns a bounded, specific list of gaps and loops back into
`execute` with those gaps appended as a system nudge, up to `VERIFY_MAX_REVISIONS=2`. This is the
"critic loop" the evaluator asked for, scoped so it can't run away.

*Files:* `agent/graph.py` (new node + conditional edge + a `revision_count` in `AgentState` + the
deep-research gate), `constants.py` (`VERIFY_MAX_REVISIONS=2`).

### O.4 — Nudge decomposition for heavy analytical prompts *(fixes RC-4)*

Strengthen the `plan_node` / orchestrator system prompt so multi-part analytical prompts are
told to delegate discrete research sub-tasks to `researcher` rather than firing one-off
`web_search` calls, and to treat each numbered plan step as a unit of work. Keep delegation the
model's decision (don't hard-wire a pipeline), but make the strong default explicit. Re-evaluate
after O.1–O.3; this may prove unnecessary once synthesis and extraction are fixed.

*Files:* `agent/graph.py` (`_PLAN_SYSTEM_PROMPT` and execute-loop system framing).

---

## 5. Sequencing & effort

Do them in root-cause priority; each is independently shippable and independently testable.

1. **O.1** first — highest impact, smallest diff, reverses a known regression.
2. **O.2** next — the biggest lever on factual grounding.
3. **O.3** — catches what O.1/O.2 still miss; most new code.
4. **O.4** — cheap, do last, may be a no-op after the above.

Re-run the green-hydrogen benchmark after O.1, after O.2, and after O.3 to attribute the gain
to each change rather than bundling them.

## 6. Test gates (per `.claude/rules/testing.md`)

- Backend-only diffs (O.1, O.2, O.4): `docker compose exec backend pytest -n auto`. New/updated
  tests: synthesis picks the `research` tier at close-out (O.1); failover-below-floor emits the
  trace warning (O.1); `web_search`→`fetch_url` auto-fetch produces body-text observations, all
  provider calls mocked, no real network (O.2); verifier detects a missing required constraint
  and loops exactly once, never more (O.3).
- O.3 touches `AgentState` / graph shape → run the full backend suite at step close, plus a
  frontend check only if the trace event shape changes (`events.py` ↔ `client.ts` contract).
- **Live regression gate:** the green-hydrogen prompt is the acceptance test. Target: named a
  *distinct* real second port, attempted the distance estimate, tracked a real Reliance/Adani
  project with a figure, every data point cited. Runs on the user's BYOK/search keys — this is a
  manual checklist item, same handling as A.9/M.7.

## 7. Decisions — LOCKED 2026-07-14

1. **Synthesis model (O.1):** O.1-a — dedicated final synthesis pass on `research` tier. ✅
2. **Verifier scope (O.3):** deep-research requirements only, 1–2 revision passes. ✅
3. **Cost/latency ceiling:** none — **quality over speed**. Heavy turns may take as long as needed
   (extra synthesis pass + page fetches + verify loop all permitted). ✅
4. **Research-tier model:** do NOT assume `deepseek-r1`. Locked pick: **`glm-4.7` primary, `deepseek-r1`
   fallback** for `final_heavy` synthesis. Rationale and the full benchmark-driven registry
   recommendation are in Appendix A below. The registry change itself is **implementation, to be applied
   later via `.claude/skills/registry-refresh`** — not part of writing this plan. ✅

---

## Appendix A — Benchmark-driven registry-refresh recommendation (NOT yet applied)

Research done 2026-07-14 (Cowork session, web sources). This is a **recommendation for a future
registry-refresh step**, captured here so O.1 has a concrete model target. It is *not* an executed
change — apply it through the `registry-refresh` skill, with the seed-parity caveat below.

### A.1 Key finding

The failed benchmark run is partly explained by a **mis-tier**: `glm-4.7` — the model that drove the
whole turn — was tagged `capability_level: "fast"`, but it is a March-2026 Z.ai frontier model with
reliable tool use, multi-turn reasoning, and ~1,000–1,700 t/s on Cerebras. Meanwhile the final report
was synthesized by `llama-3.3-70b`, now the **weakest** active chat model (Groq throttled it to
100k tok/day; superseded by newer models). Failover cascaded from a strong-but-mislabeled model down
to a genuinely weak one.

### A.2 Recommended capability_level re-tiering (existing models)

| Model | Provider (active) | Current tier | Recommended | Why |
|---|---|---|---|---|
| `glm-4.7` | Cerebras | `fast` | **`research`** | Frontier reasoning + reliable tools + fast. Best synthesis model available. |
| `llama-3.3-70b` | Groq, HF | `balanced` | **`fast`** | Dated; now the weakest active model. |
| `gpt-oss-120b` | Cerebras (+Groq) | `balanced` | `balanced` (keep) | ~1,800 t/s, Apache-2.0, reliable tools — ideal orchestrator. |
| `deepseek-r1` | HF | `research` | `research` (keep) | Strong math reasoning, but slow + verbose `<think>`; use as research *fallback*, not primary synth. |
| `gemini-2.5-flash` | Google | `balanced` | `balanced` (keep) | Fine; superseded by Gemini 3 Flash on free tier. |
| `gemini-2.5-flash-lite` | Google | `fast` | `fast` (keep) | Fast orchestrator floor. |

### A.3 New models to add (all `active:false` until provider_model_id + limits verified live)

- **`gemini-3-flash`** (Google) — new free-tier default, early 2026. Verify exact model id + RPD in AI Studio.
- **`gpt-oss-120b` Groq endpoint** — `openai/gpt-oss-120b`, ~200k tok/day free (adds a 2nd provider to an existing model).
- **`deepseek-r1-distill`** (Groq, `deepseek-r1-distill-llama-70b`) — faster distilled reasoning; verify id/limits.

Do NOT add `llama-4-scout` or `qwen3-32b` — Groq **deprecated** both 2026-06-17.

### A.4 Two implementation gotchas (found while researching)

1. **`ROLE_LEVELS` collision (code, Phase O):** `ROLE_LEVELS["orchestrator"]="fast"`. If `glm-4.7`
   moves out of `fast`, orchestration falls to `gemini-2.5-flash-lite` alone. So O.1 must also flip
   `ROLE_LEVELS["orchestrator"]` → `"balanced"` (→ `gpt-oss-120b` drives the tool loop) while
   `final_heavy="research"` (→ `glm-4.7`) does synthesis. This is the clean re-separation of the two
   roles Phase N collapsed.
2. **`seed.py` parity (data):** `tests/test_registry.py` calls `seed_registry()`, which seeds from
   `registry/seed.py`'s `INITIAL_MODELS`/`INITIAL_ENDPOINTS`. A prior dev_log entry (2026-07-14) shows
   these drifted from the JSON and broke the gate. **Editing the JSON files alone is insufficient** —
   `seed.py` must be updated in lockstep, or the registry test fails. The `registry-refresh` skill's
   "data files only" rule is in tension with this; resolve it when applying, not here.

### A.5 Rate limits — unverified

Free-tier RPM/RPD/TPM/TPD could not be verified from here (needs the provider consoles / AI Studio on
your machine; keys must not be echoed). Keep existing limits; verify new-endpoint limits live before
setting `active:true`.
