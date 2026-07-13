# Plan: Chat Agent Refinement — Tools, Router, Orchestrator, Subagents

*Branch: dev. Status: planned 2026-07-13. Not started.*
*Tracker: register as Phase A in `workspace/status/build_tracker.md` when work begins.*

> **DEPENDENCY: this plan assumes `plan_memory_scoping.md` (Phase M) is FULLY
> IMPLEMENTED.** Everywhere a paragraph relies on Phase M behavior it is tagged
> **[Phase M]**. This plan will be refined once Phase M is actually built — the
> [Phase M] tags mark exactly which assumptions to re-verify at that point. Do not
> start this plan before Phase M is done.

> **This plan is prescriptive.** All design decisions are final and locked with the
> user. Implement exactly as written — do not substitute alternative designs, add
> options, or re-open decisions. If something written here is impossible or
> contradicts the codebase, stop and ask the user; do not improvise. Where the plan
> names a constant, file, route, or semantic, use exactly that.

---

## 1. Problem

The current LangGraph agent (`agent/graph.py`) is a 5-node loop whose action protocol
is **hand-parsed JSON in plain text** (ReAct-style) — fragile with fast models and a
hard ceiling on orchestration quality. Its only actions are `search_memory`,
`ask_model`, `final`. It has no internet access, no document retrieval (uploads are
whole-doc-injected into context), no difficulty-based model routing (only static
`PURPOSE_TO_LEVEL`), no delegation, no budgets, and traces vanish on reload.

## 2. Decisions (locked 2026-07-13)

| # | Decision | Choice |
|---|---|---|
| 1 | Action protocol | **Native OpenAI-compatible tool/function calling** replaces the hand-rolled ReAct JSON parser. All providers PAWN routes (Groq, Cerebras, Gemini OAI-compat, HuggingFace, GitHub, OpenRouter) speak this wire format. |
| 2 | Internet access | `web_search` + `fetch_url` tools. Search provider is **BYOK** (user adds a Tavily or Brave key in Settings, like LLM keys). No self-hosted search infra. |
| 3 | Documents | **`doc_search` replaces whole-doc injection.** Uploads are chunked + indexed into the scoped RAG **[Phase M]** with `kind='document'`; the agent retrieves relevant parts. |
| 4 | Model routing | **Heuristic-first difficulty classifier with fast-LLM fallback** for ambiguous cases, plus **per-role model levels** (orchestrator/summarizer on fast models, heavy reasoning on strong ones). User's explicit model pick in the UI always wins for the final answer. |
| 5 | Orchestration | Plan → execute (tool loop) → final, with a **direct-answer fast path** that skips all orchestration for simple messages. Budgets and iteration caps everywhere. |
| 6 | Subagents | **Fixed presets only** (`researcher`, `summarizer`, `coder`), invoked by the orchestrator as tools, **strictly sequential** (never parallel — BYOK free-tier rate limits and the 1-vCPU box), each with its own bounded inner loop and model level. User-defined agents deferred. |
| 7 | Trace | **Persisted** — agent steps/tool calls/citations survive reload (stored with messages on Drive, cached client-side). |
| 8 | Deferred | `generate_image` chat tool, sandboxed code execution, user-defined agents, per-message "force web search" toggle. See §9. |

## 3. Architecture overview

```
user msg ──> classify (router: light/heavy + needs_agent?)
   ├─ simple ──> direct_answer (stream immediately, zero agent overhead)
   └─ complex ─> plan ──> execute loop (native tool calls, budgeted)
                              │  tools: web_search, fetch_url, search_memory,
                              │         doc_search, calculator, get_datetime,
                              │         delegate_researcher, delegate_summarizer,
                              │         delegate_coder
                              └─> final (streams answer + citations)
```

Tool results are observations; tool errors are observations too (agent adapts, never
crashes). Every step/tool-call/citation is emitted as SSE (live trace) AND persisted
(reload-safe trace).

---

## 4. Implementation steps

### A.1 — Native tool calling in the provider layer

- `core/llm_core.py`: new async function `chat_complete(model_url, model_name, headers,
  messages, tools=None, tool_choice="auto") -> dict` — **non-streaming** completion
  returning the full first choice (`message.content`, `message.tool_calls`). Same
  provider detection/wire format as the existing streaming path. Agent-internal steps
  (plan, tool decisions) use this; **only the final user-facing answer uses the
  existing streaming path** (which stays untouched).
- `core/normalize.py`: new `chat_complete(model_id, messages, resolver, rate_limiter,
  user_id=None, tools=None) -> dict` wrapping the above with the same
  resolver/failover/rate-limit handling as `chat_stream`. Routes and the agent import
  from `normalize` only (absolute rule #1 — `llm_core` is never called directly).
- Registry: `ModelEntry` gains `supports_tools: bool = True` (data field in
  `data/registry/models.json`); set `false` for any model that fails tool-calling in
  practice. `resolver.pick_model_by_capability` gains an optional
  `require_tools: bool = False` filter; the agent passes `True` for orchestrator picks.
- Tests: `chat_complete` provider-mocked (tool_calls parsing, no-tools passthrough,
  failover on 429), `require_tools` filtering.
- *Demo:* a mocked model returning a `tool_calls` delta round-trips into a parsed dict.

### A.2 — Tool layer

- New package `backend/app/agent/tools/`:
  - `base.py`: `ToolSpec` dataclass — `name`, `description`, `parameters` (JSON
    schema dict, OAI format), `handler: async (args: dict, ctx: ToolContext) -> str`.
    `ToolContext` carries `user_id`, `scope_type`, `scope_id` **[Phase M]**,
    `resolver`, `rate_limiter`.
  - `registry.py`: `get_tools(ctx) -> list[ToolSpec]` — assembles the per-request
    toolset (e.g. `web_search` only present if the user has a search key configured;
    `search_memory`/`doc_search` only when scope is not None **[Phase M]**, i.e.
    stateless chats get no memory tools).
  - `execute.py`: `run_tool(spec, args, ctx) -> str` — wraps every handler in
    `asyncio.wait_for(..., TOOL_TIMEOUT_SECONDS)`; ANY exception/timeout returns the
    string `"TOOL_ERROR: <short message>"` as the observation. Tools never raise into
    the graph.
- Constants (`app/constants.py`): `TOOL_TIMEOUT_SECONDS = 20`.
- Simple tools included here: `calculator` (safe arithmetic via `ast.literal_eval`-based
  evaluator — **never `eval()`**, per security rules) and `get_datetime` (current UTC +
  user-local ISO strings).
- Tests: tool registry assembly (with/without search key, with/without scope), timeout
  → `TOOL_ERROR`, calculator safety (rejects non-arithmetic expressions).

### A.3 — Internet access: `web_search` + `fetch_url`

- **BYOK search keys**: add `tavily` and `brave` to `core/key_store.py`'s
  `VALID_PROVIDERS`. `ApiKeysSection.tsx` gains a "Search" group with both rows (same
  save/remove UX as LLM keys). Preference order: Tavily if configured, else Brave. If
  neither: `web_search` is absent from the toolset and the agent prompt says so (it
  answers from its own knowledge; no error).
- `tools/web_search.py`: Tavily `POST https://api.tavily.com/search` (or Brave
  `GET https://api.search.brave.com/res/v1/web/search`), `WEB_SEARCH_MAX_RESULTS = 5`;
  observation = numbered list of `title — url — snippet`. HTTP via `httpx.AsyncClient`
  with the tool timeout.
- `tools/fetch_url.py`: `httpx` GET + `trafilatura` extraction (add to
  `requirements.txt`), truncated to `FETCH_MAX_CHARS = 8000`. **SSRF guard (security
  rules apply):** scheme must be http/https; resolve the hostname and reject private/
  loopback/link-local ranges (`ipaddress` stdlib) BEFORE requesting; no redirects
  followed across the guard (re-check per redirect, `max_redirects=3`). Never fetch
  URLs pointing at the backend's own network.
- **Citations**: `events.py` gains
  `citation_event(url, title)` → `{"type": "citation", "url": ..., "title": ...}`.
  The execute loop emits one per distinct URL actually used (searched-and-fetched or
  present in final answer). Frontend: `client.ts` `onCitation` callback; `Message.tsx`
  renders source chips under the answer (favicon-less, `title` text, opens in new tab).
- Tests: provider-mocked search/fetch; SSRF guard unit tests (localhost, 10.x, 169.254,
  redirect-to-private all rejected); key-missing → tool absent.
- *Demo:* ask a current-events question with a Tavily key configured → answer with
  source chips.

### A.4 — `doc_search` (replaces whole-doc injection) **[Phase M]**

- Upload path (`routes/upload.py`): after extracting text (existing pdfplumber path),
  ALSO chunk it with Phase M's `memory/chunker.py` and index via `memory/indexer.py`
  into `memory_chunks` with `kind='document'`, `doc_id=<doc id>`, and the uploading
  chat's scope (`resolve_scope`) **[Phase M — schema columns `kind`/`doc_id` and the
  `match_kind` function param are pre-provisioned in plan_memory_scoping.md §4]**.
  Doc files themselves stay in `PAWN/uploads/` (rebuild source for doc chunks =
  re-chunk the stored doc text, not a rag jsonl).
  **Draft-chat edge (locked rule):** uploading a document from a draft chat
  (PERF-2a — no server-side conversation yet) first promotes the draft exactly as
  sending a first message does (client sends its generated `conversation_id`; the
  upload route lazy-creates the conversation the same way `/chat` does), THEN
  indexes into that chat's scope. A doc upload therefore always has a scope; no
  unscoped document rows can exist.
- `chat.py`: DELETE the whole-doc system-message injection path. `doc_id` on a request
  now only records the attachment (so the doc is indexed to that chat's scope);
  content reaches the model exclusively via `doc_search`.
- `tools/doc_search.py`: scoped retrieve with `match_kind='document'` **[Phase M]**;
  observation = top chunks with doc filename prefixes.
- `tools/search_memory.py`: Phase M's scoped retrieve with `match_kind='message'`
  (this replaces the graph-internal retrieve call as the tool-layer wrapper).
- A chat's `rebuild_index` **[Phase M]** must also re-chunk that scope's documents:
  extend Phase M's `rebuild_index` to re-read docs by `doc_id` from `PAWN/uploads/`.
- Tests: upload → document chunks indexed with correct kind/scope; doc_search retrieves
  only documents, search_memory only messages; cross-scope doc isolation.
- *Demo:* upload a long PDF → ask a question about page-N content → agent calls
  doc_search, answers, whole doc never enters context.

### A.5 — Model router

- New `backend/app/core/router.py`:
  - `classify(messages, has_doc, has_tools_likely) -> RouteDecision` where
    `RouteDecision = {"difficulty": "light"|"heavy", "needs_agent": bool}`.
  - **Heuristic tier (rules, exact):** heavy if any of — total user text >
    `ROUTER_HEAVY_CHAR_THRESHOLD = 1500`; contains a fenced code block; contains any of
    the keyword set {"plan", "analyze", "debug", "prove", "compare", "research",
    "step by step", "why"} (case-insensitive, word-boundary); a doc is attached; the
    previous assistant turn used tools. Light if total user text <
    `ROUTER_LIGHT_CHAR_THRESHOLD = 200` AND none of the above. `needs_agent` = heavy,
    OR the message contains a URL, OR (search key configured AND message asks about
    time-sensitive facts per keyword set {"latest", "today", "current", "news",
    "price", "202"}).
  - **LLM fallback tier:** anything not decided above → one `chat_complete` call on
    the `fast` capability level with a fixed classification prompt returning strictly
    `light` or `heavy` (single token; on any parse failure default `heavy`,
    `needs_agent=True` — fail toward capability, not away).
  - `ROLE_LEVELS` dict (constants): `{"orchestrator": "fast", "final_light": "fast",
    "final_heavy": "research", "summarizer": "fast", "titler": "fast",
    "subagent_researcher": "fast", "subagent_coder": "research",
    "subagent_summarizer": "fast"}` — resolved through
    `resolver.pick_model_by_capability(level, require_tools=...)`.
  - **User override:** if the request carries an explicit `model_id` the user picked in
    the ModelSwitcher, that model is used for the FINAL answer regardless of
    difficulty; the router still governs all internal (orchestrator/subagent/
    summarizer) calls.
- Tests: rule-tier cases (each trigger), fallback invoked only when rules abstain,
  parse-failure defaults heavy, user override respected.
- *Demo:* "hi" streams instantly via a fast model; "research and compare X vs Y" runs
  the full agent on a heavy model.

### A.6 — Orchestrator: graph v2

- `agent/graph.py` rebuilt (same file, LangGraph kept) with nodes:
  1. `classify` — calls `router.classify`; writes `difficulty`, `needs_agent`,
     `scope_type`/`scope_id` **[Phase M]** into `AgentState`.
  2. `direct_answer` — `needs_agent=False` path: single streaming call (existing
     `chat_stream`), rolling summary as today, no tools, no plan. THE fast path —
     most messages take it.
  3. `plan` — one `chat_complete` (orchestrator level, tools listed in prompt but
     `tool_choice="none"`): produces a short numbered plan (≤5 steps) written to
     `AgentState.plan` and emitted as a `step` event. Skipped (empty plan) when
     `difficulty="light"` but `needs_agent=True` (e.g. a simple URL fetch).
  4. `execute` — the tool loop: `chat_complete(..., tools=get_tools(ctx))`; each
     returned tool_call → `run_tool` → append observation as a `role:"tool"` message;
     repeat until the model returns no tool_calls, or `AGENT_MAX_ITERATIONS = 8`
     is hit, or the token budget `AGENT_MAX_TOKENS = 24000` (sum of usage across
     internal calls) is exceeded — budget exhaustion appends a system nudge
     "budget exhausted — answer with what you have" and proceeds to final.
  5. `final` — streams the answer with the existing `chat_stream` on the
     user-picked model (or `final_light`/`final_heavy` level), context = original
     messages + rolling summary + a compact digest of tool observations (NOT the raw
     full observations — the orchestrator's last message serves as the digest).
- `AgentState` (rewrite): `messages`, `user_id`, `conversation_id`, `scope_type`,
  `scope_id` **[Phase M]**, `difficulty`, `needs_agent`, `plan: list[str]`,
  `tool_log: list[dict]` (name, args, observation, elapsed_ms, agent),
  `tokens_used: int`, `citations: list[dict]`.
- The old `load_context`/`agent`/`search_memory`/`ask_model` nodes, `build_agent_prompt`
  ReAct protocol, and `route_action` JSON parsing are **deleted**. `ask_model`'s
  purpose (consult a specific model) is subsumed by per-role routing.
- SSE: existing `step`/`model_call`/`provider_switch` events kept; `step` payload
  gains `agent: str` (`"main"` here; subagent names in A.7) and `plan` steps are
  emitted as steps. `memory_hit` **[Phase M]** is emitted when `search_memory`/
  `doc_search` tools return hits (scope + source_conv_id fields per Phase M).
- Tests: `test_agent.py` rewritten — direct path taken for light messages; tool loop
  executes mocked tool_calls; iteration cap; budget cap; tool error observed not
  raised; final streams.
- *Demo:* trace shows plan → tool calls → final for a complex question; "hello"
  produces zero agent overhead.

### A.7 — Preset subagents

- New `agent/subagents.py`: `SUBAGENTS` dict — exactly three presets, each exposed to
  the orchestrator as a tool named `delegate_<name>(task: str) -> str`:
  - `researcher` — system prompt: gather facts with sources; tools: `web_search`,
    `fetch_url` only; level `subagent_researcher`; returns a sourced digest.
  - `summarizer` — no tools; level `subagent_summarizer`; condenses text handed to it.
  - `coder` — no tools; level `subagent_coder` (heavy); writes/reviews code.
- Implementation: `run_subagent(name, task, ctx) -> str` — its own fresh message list
  (preset system prompt + task), its own `chat_complete` tool loop bounded by
  `SUBAGENT_MAX_ITERATIONS = 5` and sharing the parent's token budget counter
  (`tokens_used` is one counter for the whole request). **Strictly sequential**: it
  runs inline inside the parent's `execute` iteration — no `create_task`, no
  parallelism, ever (decision #6). Citations found by `researcher` propagate to the
  parent's `citations`.
- Subagent steps/tool calls emit `step` events with `agent: "<name>"`; the frontend
  renders them nested (A.8).
- Depth guard: subagents get NO `delegate_*` tools (max depth 1, structurally).
- Tests: delegation round-trip (mocked); shared budget decrements; researcher toolset
  restricted; no delegate tools inside a subagent.
- *Demo:* "research X and write a summary" → trace shows `main` delegating to
  `researcher` (nested search/fetch steps) then composing.

### A.8 — Trace persistence + frontend

- **Persistence**: assistant records in `messages.jsonl` **[Phase M layout —
  `chats/`/`projects/` paths]** gain an optional `trace` field: ordered list of
  entries `{kind: "step"|"tool"|"citation"|"model_call", agent, ...payload}`, capped
  at `TRACE_MAX_ENTRIES = 50` (oldest dropped). Written in `chat.py`'s persist-turn
  block from `AgentState.tool_log`/`citations`. `load_messages` returns it; no schema
  version bump needed (absent field = no trace).
- **Client cache**: `conversationCache` currently drops traces (known issue) — the
  message shape it stores gains `trace`, so traces survive reload from BOTH server and
  cache.
- `types.ts`: `TraceEntry` union type; `Message` gains `trace?: TraceEntry[]`,
  `citations?: {url, title}[]`.
- `client.ts`: `StreamChatCallbacks` gains `onToolCall(name, agent)` and
  `onCitation(url, title)`; the `switch(type)` dispatch extended for the new/extended
  event payloads (`step.agent`, `citation`, `memory_hit.scope` **[Phase M]**).
- **Streaming presentation (Claude-app style — locked with user 2026-07-13):**
  extract `components/TraceView.tsx` from `Message.tsx` (which would exceed 150
  lines). Two visual registers in one assistant message:
  - *Agent activity — lighter text:* while the stream is live, each trace entry
    renders inline, in order, ABOVE the growing answer, in muted styling
    (`text-theme-muted`, smaller size — same register as the existing metadata row).
    Entries appear as they arrive: plan lines, then tool cards with a
    present-tense label while running ("Searching the web…", "Reading page…",
    "Searching memory…", "Delegating to researcher…") that flips to past tense +
    elapsed ms when its observation lands. Subagent activity renders nested
    (indented, grouped under a muted `researcher`/`coder`/`summarizer` header).
  - *Reply — darker text:* the final answer streams in the normal message
    foreground color below the activity block. Direct-answer path (no agent) has
    no activity block at all.
  - *Auto-collapse:* when the `done` event arrives, the activity block collapses
    to a single muted summary row — "N steps · M tool calls · K sources · Xs" —
    with a chevron toggle to re-expand. Collapsed is the default state for
    historical messages too (re-expansion renders from the persisted `trace`).
    This extends the existing R5 auto-collapse behavior; the old "Agent Execution
    N steps" row is replaced by this summary row.
  - Citation chips render under the reply body (outside the collapsible block —
    sources stay visible when the trace is collapsed).
- Settings: A.3's search-key rows (this step just verifies they render with the final
  key list).
- Gate: `tsc` zero errors, `npm run build` clean.
- *Demo:* ask a tool-using question → muted activity lines stream in above the
  darker reply, auto-collapse to the summary row on completion, chevron re-expands;
  reload the page → summary row + full trace + citation chips still there.

### A.9 — Tests, review, live verify

- Full backend suite green; frontend build clean (project gates).
- code-reviewer + security-auditor via the `build-step` skill — auditor is MANDATORY
  here (new outbound HTTP from user-influenced URLs: the SSRF guard, key handling for
  search providers).
- Live verification checklist:
  1. "hello" → instant streamed reply, no plan/tool steps in trace.
  2. Current-events question + Tavily key → web_search + fetch_url in trace, correct
     answer, source chips, citations persist after reload.
  3. No search key → same question answers from model knowledge, no error surfaced.
  4. Long PDF uploaded → doc question answered via doc_search; context window stays
     small (verify via token counts in trace).
  5. "Research X vs Y and summarize" → researcher delegation visible, nested trace,
     sequential execution (no interleaving), budget respected.
  6. Force a tool failure (bad URL) → agent recovers and answers.
  7. Rate-limit a provider mid-agent-run → failover happens inside the loop
     (provider_switch event), run completes.
  8. Model pinned in UI → final answer uses it; internal calls use router levels
     (verify via model_call events).
- Update `workspace/current_state.md` + `workspace/status/dev_log.md` (absolute rule #6).

---

## 5. Constants added (all in `app/constants.py`)

`TOOL_TIMEOUT_SECONDS = 20`, `WEB_SEARCH_MAX_RESULTS = 5`, `FETCH_MAX_CHARS = 8000`,
`ROUTER_HEAVY_CHAR_THRESHOLD = 1500`, `ROUTER_LIGHT_CHAR_THRESHOLD = 200`,
`AGENT_MAX_ITERATIONS = 8`, `AGENT_MAX_TOKENS = 24000`,
`SUBAGENT_MAX_ITERATIONS = 5`, `TRACE_MAX_ENTRIES = 50`, `ROLE_LEVELS` (dict, §A.5).

## 6. Suggested step order & sizing

A.1 → A.2 are the foundation (nothing else works without native tool calling + the
tool layer). A.3 (search) and A.5 (router) are independent of each other after that;
A.4 needs A.2 + Phase M. A.6 (graph v2) consumes everything before it. A.7 rides on
A.6. A.8 can start its persistence half any time after A.6 shapes `tool_log`. Biggest
risk concentration: A.6 (full graph rewrite). Each step = one `build-step` skill
invocation.

## 7. Risks

- [Likely] **Tool-calling quality varies by model** — free-tier fast models sometimes
  emit malformed/hallucinated tool calls even natively. Mitigations: `supports_tools`
  registry flag (A.1), unknown tool name → `TOOL_ERROR` observation, budget/iteration
  caps bound the damage.
- [Likely] **Token burn**: orchestrator + tools + subagents multiply calls against BYOK
  free tiers. The single shared budget (`AGENT_MAX_TOKENS`), sequential-only
  subagents, and the direct-answer fast path are the controls; the router keeps most
  traffic off the agent entirely.
- [Certain] **SSRF is the security surface** of this plan — `fetch_url` fetches
  user-influenced URLs from inside the VM. The A.3 guard (scheme check, private-range
  rejection, per-redirect re-check) is mandatory; security-auditor must review it.
- [Likely] **Removing whole-doc injection changes answer behavior** for short docs
  (previously fully in context, now retrieved). Accepted: chunk retrieval with
  `MEMORY_TOP_K` from a short doc effectively returns the whole doc anyway.
- [Guessing] Latency of the plan step on heavy requests (~1 extra fast-model call) is
  acceptable; if not, fold plan into the first execute call later.
- [Certain] **This plan must be refined after Phase M ships** — every [Phase M] tag is
  an assumption to re-verify against the as-built code before starting.

## 8. Explicitly out of scope (documented deferrals)

- `generate_image` tool in chat (bridge to Image Lab jobs) — deferred to a later plan.
- Sandboxed code execution — its own security project; `calculator` covers arithmetic.
- User-defined custom agents (name/instructions/tools UI) — deferred; `SUBAGENTS` dict
  is the natural extension point.
- Per-message "force web search" toggle — agent decides autonomously this plan.
- Parallel subagent execution — deliberately excluded (decision #6), not merely deferred.

## 9. Open items

None. All decisions locked with the user 2026-07-13. Any deviation an implementer
believes necessary must go back to the user first.
