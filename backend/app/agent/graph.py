"""Agent orchestrator, graph v2 (Phase A / A.6).

classify -> direct_answer (needs_agent=False, THE fast path) | plan -> execute -> final

Replaces the old hand-rolled ReAct JSON action protocol (build_agent_prompt,
route_action, the load_context/agent/search_memory/ask_model nodes) with
native tool calling (A.1), the tool layer (A.2-A.4), and the model router
(A.5). Deleted, not kept alongside.
"""

import json
import re
import sys
import time
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import StateGraph, END
from langchain_core.callbacks import adispatch_custom_event

from app.agent.oai_tools import extract_citations, to_oai_tool
from app.agent.subagents import DELEGATE_PREFIX, delegate_tool_specs, run_subagent
from app.agent.tools.base import ToolContext
from app.agent.tools.execute import run_tool
from app.agent.tools.registry import get_tools
from app.constants import AGENT_MAX_ITERATIONS, AGENT_MAX_TOKENS, ROLE_LEVELS
from app.core import normalize
from app.core.router import classify as router_classify
from app.core.router import resolve_final_model
from app.resolver.resolver import Resolver
from app.core.rate_limiter import EndpointRateLimiter
from app.exceptions import NoEndpointError, ProviderError


class DummyRateLimiter:
    def can_use(self, endpoint) -> bool: return True
    def record_call(self, endpoint_id, token_count=0): pass
    def record_429(self, endpoint_id, retry_after=60): pass
    def record_connect_failure(self, endpoint_id): pass
    def record_success(self, endpoint_id): pass

class DummyResolver:
    def pick(self, model_id, user_id=None):
        return [("https://api.google.com", "gemini-2.5-flash", {}, "ep-dummy", "google")]
    def pick_by_capability(self, level, visibility="internal", user_id=None):
        return [("https://api.google.com", "gemini-2.5-flash", {}, "ep-dummy", "google")]
    def pick_model_by_capability(self, level, visibility="internal", user_id=None, require_tools=False):
        return "gemini-2.5-flash"
    def fallback_models(self, model_id, user_id=None):
        return [model_id]


class AgentState(TypedDict):
    messages: List[Dict[str, Any]]
    user_id: Optional[str]
    conversation_id: str
    user_model_id: str
    has_doc: bool
    # Phase M (memory scoping): resolved once per request in chat.py via
    # memory.indexer.resolve_scope. None for stateless chats.
    scope_type: Optional[str]
    scope_id: Optional[str]
    # Router (A.5) output.
    difficulty: str
    needs_agent: bool
    # Orchestration state.
    plan: List[str]
    tool_log: List[Dict[str, Any]]  # {name, args, observation, elapsed_ms, agent}
    tokens_used: int
    citations: List[Dict[str, str]]
    final_answer: Optional[str]


def _resolve_deps(resolver: Optional[Resolver], rate_limiter: Optional[EndpointRateLimiter]):
    return resolver or DummyResolver(), rate_limiter or DummyRateLimiter()


async def _on_provider_switch_events(from_p: str, to_p: str) -> None:
    await adispatch_custom_event("provider_switch", {"from_provider": from_p, "to_provider": to_p})


# ── classify ──────────────────────────────────────────────────────────────

async def classify_node(
    state: AgentState,
    resolver: Optional[Resolver] = None,
    rate_limiter: Optional[EndpointRateLimiter] = None,
) -> dict:
    resolver, rate_limiter = _resolve_deps(resolver, rate_limiter)
    user_id = state.get("user_id")

    has_search_key = False
    if user_id:
        from app.core import key_store
        has_search_key = key_store.has_search_key(user_id)

    decision = await router_classify(
        state["messages"],
        has_doc=state.get("has_doc", False),
        # The previous-assistant-turn-used-tools signal needs persisted trace
        # data (A.8) to detect reliably; not available yet this session.
        has_tools_likely=False,
        resolver=resolver,
        rate_limiter=rate_limiter,
        user_id=user_id,
        has_search_key=has_search_key,
    )
    return {"difficulty": decision["difficulty"], "needs_agent": decision["needs_agent"]}


def route_after_classify(state: AgentState) -> str:
    return "plan" if state.get("needs_agent") else "direct_answer"


# ── direct_answer: the fast path, zero agent overhead ───────────────────────

async def direct_answer_node(
    state: AgentState,
    resolver: Optional[Resolver] = None,
    rate_limiter: Optional[EndpointRateLimiter] = None,
) -> dict:
    """needs_agent=False path: one streaming call, no tools, no plan, no
    extra step events -- this must incur genuinely zero agent overhead."""
    resolver, rate_limiter = _resolve_deps(resolver, rate_limiter)
    user_id = state.get("user_id")
    model_id = state["user_model_id"]

    candidates = resolver.pick(model_id, user_id=user_id)
    active_provider = candidates[0][4] if candidates else "unknown"
    await adispatch_custom_event("final_provider", {"provider": active_provider})

    async def on_model_switch(from_m, to_m):
        await adispatch_custom_event("provider_switch", {"from_provider": from_m, "to_provider": to_m})
        await adispatch_custom_event("final_provider", {"provider": to_m})

    full_response = ""
    async for token in normalize.chat_stream(
        model_id=model_id,
        messages=state["messages"],
        resolver=resolver,
        rate_limiter=rate_limiter,
        on_provider_switch=_on_provider_switch_events,
        user_id=user_id,
        on_model_switch=on_model_switch,
    ):
        full_response += token
        await adispatch_custom_event("token", {"delta": token})

    return {"final_answer": full_response}


# ── plan ──────────────────────────────────────────────────────────────────

_PLAN_SYSTEM_PROMPT = (
    "You are planning how to answer the user's request. Write a short numbered "
    "plan (at most 5 steps) describing what you'll do to gather information and "
    "answer well. Do not answer the question itself here -- only the plan."
)


async def plan_node(
    state: AgentState,
    resolver: Optional[Resolver] = None,
    rate_limiter: Optional[EndpointRateLimiter] = None,
) -> dict:
    """One chat_complete (tool_choice='none' -- tools are listed so the model
    knows what it can do later, but it must not call them here) producing a
    short plan. Skipped (empty plan) for difficulty='light' + needs_agent=True
    (e.g. a bare URL) -- no point planning a one-tool-call turn."""
    if state.get("difficulty") == "light":
        return {"plan": []}

    resolver, rate_limiter = _resolve_deps(resolver, rate_limiter)
    user_id = state.get("user_id")

    ctx = ToolContext(
        user_id=user_id, scope_type=state.get("scope_type"), scope_id=state.get("scope_id"),
        resolver=resolver, rate_limiter=rate_limiter,
    )
    tools = get_tools(ctx)
    tool_specs = [to_oai_tool(t) for t in tools] + delegate_tool_specs()

    try:
        model_id = resolver.pick_model_by_capability(ROLE_LEVELS["orchestrator"], user_id=user_id, require_tools=True)
    except NoEndpointError:
        model_id = state["user_model_id"]

    messages = [{"role": "system", "content": _PLAN_SYSTEM_PROMPT}] + state["messages"]

    tokens_used = state.get("tokens_used", 0)
    try:
        result = await normalize.chat_complete(
            model_id, messages, resolver, rate_limiter, user_id=user_id,
            tools=tool_specs, tool_choice="none",
        )
    except (ProviderError, NoEndpointError) as e:
        print(f"Plan step failed (upstream), proceeding with an empty plan: {e}", file=sys.stderr)
        return {"plan": [], "tokens_used": tokens_used}
    except Exception as e:
        print(f"Plan step failed (unexpected), proceeding with an empty plan: {e}", file=sys.stderr)
        return {"plan": [], "tokens_used": tokens_used}

    tokens_used += (result.get("usage") or {}).get("total_tokens", 0) or 0
    plan_text = (result.get("content") or "").strip()
    plan_lines = [line.strip() for line in plan_text.splitlines() if line.strip()][:5]

    if plan_lines:
        await adispatch_custom_event("step", {"label": "Plan", "detail": "\n".join(plan_lines), "agent": "main"})

    return {"plan": plan_lines, "tokens_used": tokens_used}


# ── execute: the tool loop ───────────────────────────────────────────────

_MEMORY_HIT_START_RE = re.compile(r"^-\s*\[conv:(?P<conv_id>[^\]]*)\]\s*", re.MULTILINE)


def _memory_hit_lines(observation: str) -> List[Dict[str, str]]:
    """Parses search_memory's `- [conv:<id>] <text>` markers back into per-hit
    records, so the execute loop can emit one memory_hit event per hit with
    correct source_conv_id (Phase M) instead of one flattened event for the
    whole tool call. Each hit's text runs from its marker to the start of the
    next marker (or end of string) rather than to end-of-line, since a
    retrieved chunk's text can itself contain embedded newlines. doc_search's
    `[filename] ...` observations don't carry a conv_id marker, so they get a
    single event with an empty source_conv_id."""
    starts = list(_MEMORY_HIT_START_RE.finditer(observation))
    if not starts:
        return [{"text": observation, "source_conv_id": ""}]
    hits = []
    for i, m in enumerate(starts):
        text_end = starts[i + 1].start() if i + 1 < len(starts) else len(observation)
        hits.append({"text": observation[m.end():text_end].rstrip("\n"), "source_conv_id": m.group("conv_id")})
    return hits


async def execute_node(
    state: AgentState,
    resolver: Optional[Resolver] = None,
    rate_limiter: Optional[EndpointRateLimiter] = None,
) -> dict:
    resolver, rate_limiter = _resolve_deps(resolver, rate_limiter)
    user_id = state.get("user_id")
    scope_type = state.get("scope_type")
    scope_id = state.get("scope_id")

    ctx = ToolContext(
        user_id=user_id, scope_type=scope_type, scope_id=scope_id,
        resolver=resolver, rate_limiter=rate_limiter,
    )
    tools = get_tools(ctx)
    tool_specs = [to_oai_tool(t) for t in tools] + delegate_tool_specs()
    tools_by_name = {t.name: t for t in tools}

    try:
        model_id = resolver.pick_model_by_capability(ROLE_LEVELS["orchestrator"], user_id=user_id, require_tools=True)
    except NoEndpointError:
        model_id = state["user_model_id"]

    working_messages = list(state["messages"])
    plan = state.get("plan") or []
    if plan:
        working_messages = [{"role": "system", "content": "Plan:\n" + "\n".join(plan)}] + working_messages

    tool_log: List[Dict[str, Any]] = list(state.get("tool_log", []))
    citations: List[Dict[str, str]] = list(state.get("citations", []))
    seen_urls = {c["url"] for c in citations}
    tokens_used = state.get("tokens_used", 0)

    budget_exhausted = False
    for _ in range(AGENT_MAX_ITERATIONS):
        if tokens_used >= AGENT_MAX_TOKENS:
            budget_exhausted = True
            break

        try:
            result = await normalize.chat_complete(
                model_id, working_messages, resolver, rate_limiter, user_id=user_id, tools=tool_specs,
            )
        except (ProviderError, NoEndpointError) as e:
            print(f"Execute loop chat_complete failed (upstream): {e}", file=sys.stderr)
            break
        except Exception as e:
            print(f"Execute loop chat_complete failed (unexpected): {e}", file=sys.stderr)
            break

        tokens_used += (result.get("usage") or {}).get("total_tokens", 0) or 0
        tool_calls = result.get("tool_calls")
        content = result.get("content") or ""

        if not tool_calls:
            working_messages.append({"role": "assistant", "content": content})
            break

        working_messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})

        for call in tool_calls:
            fn = call.get("function", {}) or {}
            name = fn.get("name", "")
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                args = {}

            if name.startswith(DELEGATE_PREFIX):
                subagent_name = name[len(DELEGATE_PREFIX):]
                task = args.get("task", "")
                await adispatch_custom_event(
                    "step", {"label": f"Delegating to {subagent_name}", "detail": task, "agent": "main"}
                )

                start = time.monotonic()
                sub_result = await run_subagent(subagent_name, task, ctx, tokens_used)
                elapsed_ms = int((time.monotonic() - start) * 1000)

                observation = sub_result["result"]
                tokens_used = sub_result["tokens_used"]
                tool_log.append(
                    {"name": name, "args": args, "observation": observation, "elapsed_ms": elapsed_ms, "agent": "main"}
                )
                # Nested subagent tool calls, tagged with their own agent name (A.8 renders these nested).
                tool_log.extend(sub_result["tool_log"])
                for citation in sub_result["citations"]:
                    if citation["url"] not in seen_urls:
                        seen_urls.add(citation["url"])
                        citations.append(citation)
                        await adispatch_custom_event("citation", citation)

                working_messages.append({
                    "role": "tool",
                    "tool_call_id": call.get("id", ""),
                    "content": observation,
                })
                continue

            await adispatch_custom_event(
                "step", {"label": f"Calling {name}", "detail": json.dumps(args), "agent": "main"}
            )

            spec = tools_by_name.get(name)
            start = time.monotonic()
            if spec is None:
                observation = f"TOOL_ERROR: unknown tool '{name}'"
            else:
                observation = await run_tool(spec, args, ctx)
            elapsed_ms = int((time.monotonic() - start) * 1000)

            tool_log.append(
                {"name": name, "args": args, "observation": observation, "elapsed_ms": elapsed_ms, "agent": "main"}
            )

            if name in ("search_memory", "doc_search") and not observation.startswith("TOOL_ERROR"):
                if observation not in ("No relevant memory found.", "No relevant document content found."):
                    for hit in _memory_hit_lines(observation):
                        await adispatch_custom_event(
                            "memory_hit",
                            {"summary": hit["text"], "scope": scope_type or "", "source_conv_id": hit["source_conv_id"]},
                        )

            for citation in extract_citations(name, args, observation):
                if citation["url"] not in seen_urls:
                    seen_urls.add(citation["url"])
                    citations.append(citation)
                    await adispatch_custom_event("citation", citation)

            working_messages.append({
                "role": "tool",
                "tool_call_id": call.get("id", ""),
                "content": observation,
            })
    else:
        budget_exhausted = True

    if budget_exhausted:
        working_messages.append({"role": "system", "content": "budget exhausted — answer with what you have"})

    return {
        "messages": working_messages,
        "tool_log": tool_log,
        "citations": citations,
        "tokens_used": tokens_used,
    }


# ── final ────────────────────────────────────────────────────────────────

async def final_node(
    state: AgentState,
    resolver: Optional[Resolver] = None,
    rate_limiter: Optional[EndpointRateLimiter] = None,
) -> dict:
    resolver, rate_limiter = _resolve_deps(resolver, rate_limiter)
    user_id = state.get("user_id")

    model_id = resolve_final_model(
        state.get("difficulty", "light"), state.get("user_model_id"), resolver, user_id=user_id
    )

    # Digest, not raw observations: the tool loop's own last messages already
    # carry the assistant's synthesis of what it found; we just append a
    # compact recap so the final model doesn't have to re-derive it from a
    # long tool-call transcript.
    digest_messages = list(state["messages"])
    tool_log = state.get("tool_log", [])
    if tool_log:
        digest_lines = [f"- {t['name']}: {t['observation'][:300]}" for t in tool_log]
        digest_messages.append(
            {"role": "system", "content": "Findings from tool use this turn:\n" + "\n".join(digest_lines)}
        )

    await adispatch_custom_event("step", {"label": "Composing final answer", "detail": "", "agent": "main"})

    candidates = resolver.pick(model_id, user_id=user_id)
    initial_provider = candidates[0][4] if candidates else "unknown"
    await adispatch_custom_event("final_provider", {"provider": initial_provider})

    async def on_switch(from_p, to_p):
        await adispatch_custom_event("provider_switch", {"from_provider": from_p, "to_provider": to_p})
        await adispatch_custom_event("final_provider", {"provider": to_p})

    async def on_model_switch(from_m, to_m):
        await adispatch_custom_event("provider_switch", {"from_provider": from_m, "to_provider": to_m})
        await adispatch_custom_event("final_provider", {"provider": to_m})

    full_response = ""
    async for token in normalize.chat_stream(
        model_id=model_id,
        messages=digest_messages,
        resolver=resolver,
        rate_limiter=rate_limiter,
        on_provider_switch=on_switch,
        user_id=user_id,
        on_model_switch=on_model_switch,
    ):
        full_response += token
        await adispatch_custom_event("token", {"delta": token})

    return {"final_answer": full_response}


def build_agent_graph(
    resolver: Optional[Resolver] = None,
    rate_limiter: Optional[EndpointRateLimiter] = None,
) -> StateGraph:
    resolver, rate_limiter = _resolve_deps(resolver, rate_limiter)

    graph = StateGraph(AgentState)

    from functools import partial
    graph.add_node("classify", partial(classify_node, resolver=resolver, rate_limiter=rate_limiter))
    graph.add_node("direct_answer", partial(direct_answer_node, resolver=resolver, rate_limiter=rate_limiter))
    graph.add_node("plan", partial(plan_node, resolver=resolver, rate_limiter=rate_limiter))
    graph.add_node("execute", partial(execute_node, resolver=resolver, rate_limiter=rate_limiter))
    graph.add_node("final", partial(final_node, resolver=resolver, rate_limiter=rate_limiter))

    graph.set_entry_point("classify")
    graph.add_conditional_edges(
        "classify", route_after_classify, {"direct_answer": "direct_answer", "plan": "plan"}
    )
    graph.add_edge("direct_answer", END)
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "final")
    graph.add_edge("final", END)

    return graph
