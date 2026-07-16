# Phase F-7 — Agent Half-Generation / Empty Reply Fix

**Status:** PLANNED. **Branch:** `dev`. **Folder:** `workspace/plan/chat/`
**Date:** 2026-07-15

## 1. Why this plan exists

On deployed production code when agents are involved (e.g. during a heavy or tool-using chat turn), the final response sometimes cuts off right after displaying "Composing final answer". The user is left with no prose reply in the message bubble, even though the trace details and citations are rendered.

### Root Cause Analysis

1. **Messages Context Ends with `assistant`:** In `execute_node` (`graph.py`), at the end of the orchestrator loop, the orchestrator appends its own draft text to the message list:
   `working_messages.append({"role": "assistant", "content": content})`
   When `stream_iteration(use_tools=False)` is then called to do the dedicated closing synthesis pass, the messages list sent to the LLM ends with a message whose role is `assistant`.
2. **API Rejection / Empty Responses:** For many production providers (such as Gemini/Google via their OpenAI-compatibility layer), sending a completions payload where the final message is an `assistant` message either returns a `400 Bad Request` or causes the LLM to return an empty response immediately because it assumes the assistant has already finished generating its response.
3. **Swallowed / Buffered Token Drops:** If the closing synthesis returns empty content, `verify_draft` gets set to `""`. The `verify_node` runs, fails verification (since the draft is empty), and loops. After `VERIFY_MAX_REVISIONS=2` revisions, `verify_node` accepts the empty draft and calls `accept()`. Because the draft is empty (`""`), `accept()` dispatches zero `token` events. The request finishes successfully but streams no reply content, leaving the user with an empty reply.

**Verified against current code (2026-07-15 refinement pass):** the root cause holds up
exactly as described. `agent/graph.py:484` appends `{"role": "assistant", "content":
content}` to `working_messages` on a clean tool-loop stop; on a heavy turn this same
`working_messages` list is passed straight into the closing-synthesis `stream_iteration`
call (`graph.py:612-616`) with **no filtering of the trailing assistant-role message and
no try/except around that call** — both confirmed unimplemented today, so this plan's two
fixes are both real, not already covered elsewhere.

## 2. Proposed Changes

### 2.1 Backend

#### [MODIFY] [graph.py](file:///c:/Users/harsh/Desktop/PAWN/backend/app/agent/graph.py)
- Refactor how `working_messages` is constructed before the closing synthesis pass in `execute_node`:
  - **Option A:** Avoid appending the orchestrator's own draft as a final `assistant` message in `working_messages`. Instead, keep the list ending with the last `tool` message (if tools were called) or the `user` message.
  - **Option B:** Convert the orchestrator's draft into a `system` instruction context (e.g., `"Orchestrator draft: <content>\nBased on the tool results and request, write the final response."`) so the prompt alternates cleanly and the final LLM is called with a `user` or `system` message at the tail.
- Wrap the closing synthesis `stream_iteration` call in a `try/except (ProviderError, NoEndpointError, Exception)` block. If it fails, log the error and fall back to using the orchestrator's own loop-generated draft rather than failing the response entirely.

#### [MODIFY] [retrieve.py](file:///c:/Users/harsh/Desktop/PAWN/backend/app/memory/retrieve.py) / [graph.py](file:///c:/Users/harsh/Desktop/PAWN/backend/app/agent/graph.py)
- Ensure that if `verify_draft` is empty or missing, `verify_node` fails gracefully or defaults to streaming whatever content was accumulated rather than returning an empty response.

## 3. Verification Plan

### Automated Tests
- Add a test in `backend/tests/test_agent.py` where `execute_node` completes and the final payload sent to `normalize.chat_stream_with_tools` is inspected.
- Assert that the final message in `working_messages` is NOT an `assistant` role message.
- Verify that if the synthesis model fails, the node falls back to emitting the loop's original draft answer.

### Manual Verification
- Ask a heavy or tool-using query in the UI on a deployed VM (e.g., geopolitical or search-heavy query).
- Confirm that the final synthesized response streams fully and renders inside the message bubble, and that "Composing final answer" is followed by the actual answer.
