# Plan: Interleaved Agent Streaming (execute+final merge)

*Branch: dev. Status: in progress, started 2026-07-14 (Cowork session).*
*Tracker: register as Phase N in `workspace/status/build_tracker.md`.*
*Depends on: Phase A (`workspace/implemented_phases/phase_12_chat_agent_refinement.md`) — this plan modifies A.6's `execute_node`/`final_node` directly.*

## 1. Problem

User-reported: agent replies read as two separate blocks — all tool-call activity
(plan, tool cards, provider switches) rendered as one collapsed trace block above
the reply, then the entire final answer appears below it, generated only after
every tool call has already finished. Locked-in root cause (not a rendering bug):
`agent/graph.py`'s `execute_node` (the tool loop) uses **non-streaming**
`normalize.chat_complete` — it must inspect `tool_calls` before deciding what to do
next — and hands off to a **completely separate** `final_node`, which streams the
answer via `normalize.chat_stream` (no tool support) only after the tool loop is
fully done. Two disconnected LLM calls. Claude's own actual UI doesn't have this
seam because it's one continuous generation that happens to pause for a tool call
and resume — that requires the SAME call to support both streaming and tools.

## 2. Decisions (locked with user 2026-07-14)

| # | Decision | Choice |
|---|---|---|
| 1 | Scope | Merge `execute_node` + `final_node` into one streaming tool-loop node. `plan_node` and `classify_node`/`direct_answer_node` are unchanged. |
| 2 | New primitive | `llm_core.stream_chat_with_tools()` — `stream=True` + `tools=[...]` in one request; yields `{"type":"content","delta":str}` per token and a final `{"type":"done","tool_calls":[...]|None,"finish_reason":str}`. Assumes every PAWN provider (Groq, Cerebras, HuggingFace router, Google OAI-compat, OpenRouter) supports streaming+tools together — standard OpenAI wire format, unverified against live providers from the build sandbox; first real confirmation happens on the user's machine. |
| 3 | Failover | Same two-level failover as existing `chat_stream` (endpoint, then cross-model), same hard rule: once a token has reached the user for a given call, no retry/switch — a mid-stream error surfaces directly. Not a new risk; identical to today's `_stream_one_model` contract. |
| 4 | Loop shape | Each iteration: stream tokens (forwarded live as SSE `token` events) + tools; if `tool_calls` present at stream end, run them (existing `run_tool`/subagent dispatch, unchanged) and loop with the tool result appended; stop when `finish_reason` isn't tool-call-shaped, or `AGENT_MAX_ITERATIONS`/`AGENT_MAX_TOKENS` hit (same caps as today, same budget-exhausted nudge). |
| 5 | Frontend data model | `Message.content: string` + separate `trace: TraceEntry[]` (trace always renders above content) can't represent "text, then a tool card, then more text." Replaced with an ordered `segments: Segment[]` (`{type:'text', content}` \| `{type:'tool', entry: TraceEntry}`), appended in true arrival order. `citations`/`viaProvider` stay as separate fields (unchanged, not part of the interleaved flow). |
| 6 | Trace persistence | `_build_trace`/`_prior_turn_used_tools` (routes/chat.py) and the reload/localStorage cache path keep working from `tool_log`/`citations` in `AgentState` exactly as today — the merge doesn't change what's persisted, only how the live SSE stream is shaped and how the frontend renders it while streaming. |

## 3. Architecture

Before:
```
plan ──> execute (chat_complete, non-streaming, loops on tool_calls)
              └─> final (chat_stream, no tools, separate call, streams whole answer)
```

After:
```
plan ──> execute (chat_stream_with_tools, ONE call type, loops on tool_calls,
                   streams tokens live on every iteration including the last)
```

`final_node` is deleted; `execute_node` absorbs its responsibility (picking
`resolve_final_model`'s model isn't relevant anymore — every iteration uses the
same orchestrator-capable model that can call tools, consistent with how
`execute_node` already picks its model today via
`resolver.pick_model_by_capability(ROLE_LEVELS["orchestrator"], require_tools=True)`).
The graph edge `execute -> final -> END` becomes `execute -> END`.

## 4. Files touched

- `backend/app/core/llm_core.py` — new `stream_chat_with_tools()`.
- `backend/app/core/normalize.py` — new `chat_stream_with_tools()` wrapping it with failover, mirroring `chat_stream`'s `_stream_one_model` pattern.
- `backend/app/agent/graph.py` — `execute_node` rewritten to the streaming loop; `final_node` deleted; `build_agent_graph`'s edges updated (`execute -> END`, no `final` node).
- `backend/tests/test_agent.py` — execute/final tests rewritten for the merged node (pure-text stream, tool-call-mid-stream-then-continue, multi-tool-call sequence, budget/iteration caps, trace/citations shape for persistence).
- `frontend/src/types.ts` — `Message` gains `segments`.
- `frontend/src/pages/ChatPage.tsx` — SSE callbacks append to `segments` in arrival order instead of separately to `content`/`trace`.
- `frontend/src/components/Message.tsx` / `TraceView.tsx` — render by walking `segments`.
- `frontend/src/store/useConversationStore.ts` — cache round-trip (`toPersisted`/`fromPersisted`) carries `segments` alongside/instead of `trace` for the live-session cache; the *persisted* (reload) shape from the backend is unchanged (`trace`/`citations`/`content`), so reload-path rendering needs to synthesize a single-text-segment view from the persisted fields, not expect the backend to emit `segments`.

## 5. Explicitly out of scope this pass

- `plan_node` staying non-streaming (it's a short, cheap, upfront call — not part of the user's complaint).
- Subagent (`delegate_*`) calls staying non-streaming internally — a delegated subagent's own tool loop is a separate, bounded, backgrounded unit; interleaving its internal text into the parent's live stream is a bigger change not asked for here.
- Any change to `_build_trace`, the Drive persistence shape, or the reload/history rendering path — only the *live* streaming experience changes.

## 6. Verification

- Backend: rewritten `test_agent.py` cases, run via `docker compose exec backend pytest -n auto` (sandbox can partially verify syntax/logic with mocked providers, not live streaming+tools behavior against a real provider).
- Frontend: `tsc -b` + `vite build` clean.
- **Live, needs the user's machine + real BYOK keys:** send a tool-using message (e.g. the calculator prompt used earlier) and confirm text actually starts appearing before/around the tool card, not only after it — this is the one thing that cannot be verified from the build sandbox at all, since it requires a real streaming+tools response from a real provider.
