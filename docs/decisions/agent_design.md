# Agent Design
## LangGraph Graph, JSON/ReAct Protocol, Capability Routing

---

## Overview

The agent is a LangGraph `StateGraph`. It replaces the single-shot `provider → stream`
flow with a multi-step loop that can plan, retrieve, draft, critique, and synthesize.
Every step is streamed to the UI as it happens.

The agent is introduced in Phase 1.5 (Step 16) and evolves in Phase 1.6 (capability routing).

---

## Core Invariants

These never change across phases:

1. **Provider isolation:** all LLM calls go through `normalize.chat_stream` only.
   Graph nodes never call `llm_core.stream_llm` directly.

2. **User's brain writes the final answer.** The agent orchestrates sub-tasks internally.
   The model the user selected in the UI always writes the response they see. The agent
   never overrides this.

3. **JSON/ReAct protocol inside agent node.** Model outputs exactly one JSON action per turn.
   The parser extracts it. If parsing fails, output is treated as a `final` action.

4. **Hard step cap.** 8 iterations maximum. After the cap, the agent is forced to `final`.
   This prevents runaway loops.

5. **Every step emits an SSE event.** The UI trace panel shows every decision in real time.

---

## Graph Structure

```
                    ┌─────────────────┐
                    │  load_context   │  loads conversation + retrieves memory hits
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
          ┌────────►│   agent_node    │◄─────────────────────┐
          │         │  JSON/ReAct     │                      │
          │         └────────┬────────┘                      │
          │                  │ action                         │
          │         ┌────────▼────────────────────────────┐  │
          │         │         Dispatch                     │  │
          │         │  search_memory  ask_model  final    │  │
          │         └──────┬─────────────┬──────────┬─────┘  │
          │                │             │          │         │
          │    ┌───────────▼──┐  ┌───────▼─────┐   │         │
          │    │ search_memory│  │  ask_model  │   │         │
          │    │   node       │  │    node     │   │         │
          │    └───────────┬──┘  └───────┬─────┘   │         │
          │                │             │          │         │
          └────────────────┴─────────────┘          │         │
                   (loop back to agent_node)        │         │
                                                    │         │
                                           ┌────────▼────────┐│
                                           │   final_node    ││
                                           │  stream answer  ││
                                           └─────────────────┘│
                                                  (end)
```

---

## State Schema

```python
from typing import TypedDict, Annotated
from langgraph.graph import add_messages

class AgentState(TypedDict):
    conversation_id: str
    history: list[dict]           # full conversation history loaded from disk
    retrieved_memory: list[str]   # memory chunks injected from RAG
    scratchpad: list[dict]        # prior steps this turn: [{action, result}, ...]
    next_action: dict | None      # parsed JSON action from agent_node
    final_answer: str | None      # set when action == "final"
    user_model_id: str            # the user's selected model — always writes the final answer
    step_count: int               # incremented on each agent_node iteration
```

---

## Nodes

### load_context_node

```python
async def load_context_node(state: AgentState) -> AgentState:
    # 1. Load conversation messages from disk (already done by route, passed in via state)
    # 2. Retrieve memory hits for the latest user message
    hits = await retrieve(state["history"][-1]["content"], top_k=3)
    # 3. Emit memory_hit SSE events for each hit
    # 4. Return state with retrieved_memory populated
    return {**state, "retrieved_memory": [h["text"] for h in hits]}
```

### agent_node

The reasoning hub. Builds the full prompt, calls the internal LLM, parses the action.

```python
async def agent_node(state: AgentState, resolver: Resolver, rate_limiter: EndpointRateLimiter) -> AgentState:
    if state["step_count"] >= 8:
        # hard cap — force final
        return {**state, "next_action": {"action": "final", "answer": state["scratchpad"][-1].get("result", "")}}

    prompt = build_agent_prompt(
        history=state["history"],
        memory=state["retrieved_memory"],
        scratchpad=state["scratchpad"],
        available_actions=["search_memory", "ask_model", "final"],
    )

    # Route to best available fast model for agent reasoning (cheap, low-latency)
    response = ""
    async for token in normalize.chat_stream(
        model_id=resolver.pick_by_capability("fast")[0][1],
        messages=[{"role": "user", "content": prompt}],
        resolver=resolver,
        rate_limiter=rate_limiter,
    ):
        response += token

    emit_step_event("Thinking", f"step {state['step_count'] + 1}")
    action = parse_action(response)
    return {**state, "next_action": action, "step_count": state["step_count"] + 1}
```

### search_memory_node

```python
async def search_memory_node(state: AgentState) -> AgentState:
    query = state["next_action"]["query"]
    emit_step_event("Searching memory", query)
    hits = await retrieve(query, top_k=3)
    for hit in hits:
        emit_memory_hit_event(hit["text"])
    result = "\n".join(h["text"] for h in hits) or "No relevant memory found."
    scratchpad = state["scratchpad"] + [{"action": "search_memory", "query": query, "result": result}]
    return {**state, "scratchpad": scratchpad, "next_action": None}
```

### ask_model_node

```python
async def ask_model_node(state: AgentState, resolver: Resolver, rate_limiter: EndpointRateLimiter) -> AgentState:
    purpose = state["next_action"]["purpose"]
    prompt_text = state["next_action"]["prompt"]
    level = PURPOSE_TO_LEVEL[purpose]

    emit_model_call_event(model=level, purpose=purpose)
    emit_step_event(f"{'Drafting' if purpose == 'draft' else 'Critiquing'}", purpose)

    response = ""
    async for token in normalize.chat_stream(
        model_id=resolver.pick_by_capability(level)[0][1],
        messages=[{"role": "user", "content": prompt_text}],
        resolver=resolver,
        rate_limiter=rate_limiter,
    ):
        response += token
        emit_token_event(token)  # stream draft/critique tokens to trace panel

    scratchpad = state["scratchpad"] + [{"action": "ask_model", "purpose": purpose, "result": response}]
    return {**state, "scratchpad": scratchpad, "next_action": None}
```

### final_node

```python
async def final_node(state: AgentState, resolver: Resolver, rate_limiter: EndpointRateLimiter) -> AgentState:
    # Build the synthesis prompt from scratchpad results
    synthesis_prompt = build_synthesis_prompt(
        original_question=state["history"][-1]["content"],
        memory=state["retrieved_memory"],
        scratchpad=state["scratchpad"],
        # "final" action may carry an answer directly
        agent_answer=state["next_action"].get("answer", ""),
    )

    emit_step_event("Composing final answer", "")

    # The user's selected brain writes the final answer — always
    async for token in normalize.chat_stream(
        model_id=state["user_model_id"],
        messages=state["history"] + [{"role": "user", "content": synthesis_prompt}],
        resolver=resolver,
        rate_limiter=rate_limiter,
    ):
        yield token  # stream to SSE as token events
```

---

## JSON/ReAct Protocol

The agent prompt format:

```
You are an AI assistant working on a task. You must respond with exactly ONE JSON action.

## Conversation
[conversation history]

## Retrieved Memory
[memory chunks]

## Scratchpad (prior steps this turn)
[prior actions and their results]

## Available Actions
- search_memory: { "action": "search_memory", "query": "<what to look for>" }
- ask_model: { "action": "ask_model", "purpose": "draft|critique|research", "prompt": "<task for the model>" }
- final: { "action": "final", "answer": "<synthesized answer, or empty to let the main model compose>" }

Choose the next action. Output ONLY valid JSON.
```

### Parser

`app/agent/parser.py`:
```python
import json, re

def parse_action(output: str) -> dict:
    # 1. Try to find JSON in the output (handles prose + JSON mixed output)
    match = re.search(r'\{[^{}]+\}', output, re.DOTALL)
    if match:
        try:
            action = json.loads(match.group())
            if "action" in action:
                return action
        except json.JSONDecodeError:
            pass
    # 2. Fallback: treat entire output as a final answer
    return {"action": "final", "answer": output.strip()}
```

---

## Capability Routing

`app/agent/routing.py`:
```python
PURPOSE_TO_LEVEL = {
    "plan":     "fast",      # Low-cost planning; quick, high-quota models
    "draft":    "balanced",  # Most sub-task work; solid quality
    "critique": "balanced",  # Second opinion; resolver picks different provider than draft
    "research": "research",  # Deep reasoning; DeepSeek R1 etc.
    # "final"  → NOT routed here; always state["user_model_id"]
}
```

After Phase 1.6, the resolver's `pick_by_capability(level)` returns candidates sorted by
priority from the registry. If the top endpoint for "balanced" is rate-limited, the resolver
automatically returns the next one. The agent never knows which provider answered.

Before Phase 1.6, this map returns hardcoded model IDs from the registry as a placeholder:
```python
PURPOSE_TO_MODEL_ID = {
    "plan":     "gemini-2.5-flash-lite",
    "draft":    "gemini-2.5-flash",
    "critique": "llama-3.3-70b",
    "research": "deepseek-r1",
}
```

---

## Agent Prompt Engineering

### build_agent_prompt

The quality of the agent depends heavily on the prompt structure. Key decisions:

- **Scratchpad format:** each prior step shown as `ACTION: <type> | RESULT: <text>`.
  Keeps the prompt token-efficient while preserving reasoning context.

- **Action constraint:** "Output ONLY valid JSON" at the end of the prompt.
  Reduces prose-wrapping. The parser still handles fallback.

- **Step count in prompt:** "You have used X of 8 steps." Prevents the model from
  wandering when the cap is near.

- **No tool descriptions in the base prompt:** actions are simple enough that a brief
  inline description suffices. Verbose tool specs bloat the context unnecessarily.

### build_synthesis_prompt

The final answer prompt injects the scratchpad results as additional context:
```
Based on the research and drafting below, write a comprehensive answer.

## Research Summary
[scratchpad results]

## User Question
[original question]

Answer directly, clearly, and concisely.
```

The synthesis prompt goes into the conversation history as a user message. The user's
selected model responds to the full history including this synthesis context.

---

## LangGraph Setup

`app/agent/graph.py`:
```python
from langgraph.graph import StateGraph, END

def build_agent_graph(resolver, rate_limiter) -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("load_context",   partial(load_context_node))
    graph.add_node("agent",          partial(agent_node, resolver=resolver, rate_limiter=rate_limiter))
    graph.add_node("search_memory",  partial(search_memory_node))
    graph.add_node("ask_model",      partial(ask_model_node, resolver=resolver, rate_limiter=rate_limiter))
    graph.add_node("final",          partial(final_node, resolver=resolver, rate_limiter=rate_limiter))

    graph.set_entry_point("load_context")
    graph.add_edge("load_context", "agent")

    def route_action(state: AgentState) -> str:
        action = state.get("next_action", {})
        return action.get("action", "agent")  # fallback: re-run agent

    graph.add_conditional_edges("agent", route_action, {
        "search_memory": "search_memory",
        "ask_model":     "ask_model",
        "final":         "final",
    })
    graph.add_edge("search_memory", "agent")
    graph.add_edge("ask_model",     "agent")
    graph.add_edge("final",         END)

    return graph.compile()
```

Step events are emitted inside each node function via a shared SSE event queue or generator
pattern. The route handler streams events from this queue to the frontend.

---

## Frontend — Trace Panel

`src/components/TracePanel.tsx`:

```typescript
interface TraceEvent {
  type: "step" | "memory_hit" | "model_call" | "token";
  label?: string;
  detail?: string;
  summary?: string;
  model?: string;
  purpose?: string;
  delta?: string;
}

// Renders as a collapsible panel below the streaming reply bubble
// Each step event → a row: "● Searching memory: project preferences"
// Each memory_hit → a faded row: "↩ From 2026-06-07: user prefers concise answers"
// Each model_call → a row with model badge: "⚡ Drafting [balanced]"
// Draft/critique tokens stream inline in the trace, not in the main bubble
// Collapses by default once done fires; user can re-expand
```
