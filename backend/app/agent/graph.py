"""Agent orchestrator, graph v2 (Phase A / A.6; execute/final merged in Phase N).

classify -> direct_answer (needs_agent=False, THE fast path) | plan -> execute -> END

Replaces the old hand-rolled ReAct JSON action protocol (build_agent_prompt,
route_action, the load_context/agent/search_memory/ask_model nodes) with
native tool calling (A.1), the tool layer (A.2-A.4), and the model router
(A.5). Deleted, not kept alongside.

Phase N (2026-07-14): execute_node and the old final_node merged into one
streaming tool-loop node -- both used to make separate LLM calls (execute:
non-streaming chat_complete looping on tool_calls; final: a completely
separate chat_stream with no tool support), so all tool activity necessarily
finished before any reply text existed. Now every iteration streams tokens
live via normalize.chat_stream_with_tools (stream=True + tools in one call),
so text the model produces before/after a tool call is visible to the user
interleaved with the tool card, matching one continuous generation instead of
two disconnected blocks. final_node deleted; resolve_final_model (router.py)
is no longer called from here -- every iteration uses the same
orchestrator-capable, tool-supporting model picked once at the top of
execute_node.
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
from app.core.router import classify as router_classify, resolve_final_model
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
    # Router heavy-trigger: did the previous assistant turn use tools? Derived
    # in chat.py from the last persisted assistant message's `trace` (A.8) —
    # the persisted trace made this signal available, closing the "not
    # available yet" hardcoded-False gap from the A.6 session.
    has_tools_likely: bool
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
        # Derived in chat.py from the last persisted assistant message's
        # trace (A.8) — True when the prior turn actually used tools.
        has_tools_likely=state.get("has_tools_likely", False),
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

    # Best-effort "which provider is about to stream" peek for the UI's initial
    # badge -- NOT the real availability check. It only looks at model_id's own
    # endpoints, a strict subset of what chat_stream is about to try (it fails
    # over across resolver.fallback_models(model_id, ...) too). Found 2026-07-14
    # (F-1): this used to be unguarded, so a NoEndpointError here (model_id's
    # endpoints exhausted, even though a fallback model would have worked) killed
    # the whole turn before chat_stream got a chance to fail over, surfacing as a
    # generic "unexpected error" in routes/chat.py's broad except. Degrade to
    # "unknown" instead -- chat_stream's own on_provider_switch/on_model_switch
    # callbacks correct the badge the moment a real endpoint is chosen.
    try:
        candidates = resolver.pick(model_id, user_id=user_id)
        active_provider = candidates[0][4] if candidates else "unknown"
    except (ProviderError, NoEndpointError):
        active_provider = "unknown"
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
            on_provider_switch=_on_provider_switch_events,
            on_model_switch=_on_provider_switch_events,
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


# ── execute: the streaming tool loop (Phase N — merged with the old final_node)

_MEMORY_HIT_START_RE = re.compile(r"^-\s*\[conv:(?P<conv_id>[^\]]*)\]\s*", re.MULTILINE)

_TOKEN_CHARS_PER_ESTIMATED_TOKEN = 4


def _estimate_tokens(content: str, tool_calls: Optional[List[Dict[str, Any]]]) -> int:
    """Fallback token-budget estimate for a streamed iteration when the
    provider doesn't honor the OAI stream_options.include_usage flag (real
    usage is preferred -- see stream_iteration below). Rough chars/4 proxy,
    good enough for a soft AGENT_MAX_TOKENS nudge, not a billing figure."""
    raw = content + (json.dumps(tool_calls) if tool_calls else "")
    return max(1, len(raw) // _TOKEN_CHARS_PER_ESTIMATED_TOKEN) if raw else 0


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
    """The tool loop AND the user-facing answer, merged into one streaming
    call type (Phase N) -- replaces the old execute_node (non-streaming
    chat_complete tool loop) + final_node (separate chat_stream, no tools)
    split. Every iteration streams tokens live via chat_stream_with_tools
    (forwarded as SSE `token` events as they arrive, not withheld until the
    whole tool loop finishes), so text the model produces before a tool call
    (e.g. "Let me check that...") is visible to the user interleaved with the
    tool card, not only the model's final answer after every tool call has
    already resolved."""
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
    full_response = ""

    # Same F-1 fix as direct_answer_node/the old final_node: this peek only
    # checks model_id's own endpoints (a subset of what chat_stream_with_tools
    # will try via fallback_models), so it must never crash the turn on its own.
    try:
        candidates = resolver.pick(model_id, user_id=user_id)
        active_provider = candidates[0][4] if candidates else "unknown"
    except (ProviderError, NoEndpointError):
        active_provider = "unknown"
    await adispatch_custom_event("final_provider", {"provider": active_provider})

    async def on_switch(from_p, to_p):
        await adispatch_custom_event("provider_switch", {"from_provider": from_p, "to_provider": to_p})
        await adispatch_custom_event("final_provider", {"provider": to_p})

    async def on_model_switch(from_m, to_m):
        await adispatch_custom_event("provider_switch", {"from_provider": from_m, "to_provider": to_m})
        await adispatch_custom_event("final_provider", {"provider": to_m})

    # Set False at the start of every stream_iteration call, flipped True the
    # moment that call's first "content" event reaches the user. Checked by
    # the loop's except clauses below: once true, a failure in that same call
    # must propagate directly (the locked "no retry once a token has reached
    # the user" contract -- chat_stream_with_tools/_stream_one_model_with_tools
    # already honor this at their own layer, but a broad try/except one level
    # up here would otherwise silently swallow it and fall through to a fresh
    # closing call, producing partial-text-then-unrelated-answer garbage).
    content_reached_user_this_call = False

    async def stream_iteration(
        use_tools: bool,
        override_model_id: Optional[str] = None,
        override_on_model_switch=None,
    ):
        """Runs one streaming call, forwarding content live as SSE `token`
        events and accumulating tokens_used from real usage when the provider
        honors stream_options.include_usage, estimated otherwise. Returns
        (content, tool_calls). `override_model_id`/`override_on_model_switch`
        let the O.1 closing-synthesis call run on a different (upgraded)
        model with its own switch-detection hook, without duplicating the
        rest of this bookkeeping."""
        nonlocal tokens_used, full_response, content_reached_user_this_call
        content_reached_user_this_call = False
        content = ""
        tool_calls: Optional[List[Dict[str, Any]]] = None
        async for event in normalize.chat_stream_with_tools(
            override_model_id or model_id, working_messages, resolver, rate_limiter, user_id=user_id,
            tools=tool_specs if use_tools else None,
            on_provider_switch=on_switch,
            on_model_switch=override_on_model_switch or on_model_switch,
        ):
            if event["type"] == "content":
                content_reached_user_this_call = True
                content += event["delta"]
                full_response += event["delta"]
                await adispatch_custom_event("token", {"delta": event["delta"]})
            else:  # "done"
                tool_calls = event.get("tool_calls")
                real_total = (event.get("usage") or {}).get("total_tokens")
                tokens_used += real_total if real_total is not None else _estimate_tokens(content, tool_calls)
        return content, tool_calls

    answered = False
    budget_exhausted = False
    for _ in range(AGENT_MAX_ITERATIONS):
        if tokens_used >= AGENT_MAX_TOKENS:
            budget_exhausted = True
            break

        try:
            content, tool_calls = await stream_iteration(use_tools=True)
        except (ProviderError, NoEndpointError) as e:
            if content_reached_user_this_call:
                raise  # a token already reached the user this call -- no fallback, surface directly
            print(f"Execute loop chat_stream_with_tools failed (upstream), no content sent yet: {e}", file=sys.stderr)
            break
        except Exception as e:
            if content_reached_user_this_call:
                raise
            print(f"Execute loop chat_stream_with_tools failed (unexpected), no content sent yet: {e}", file=sys.stderr)
            break

        if not tool_calls:
            working_messages.append({"role": "assistant", "content": content})
            answered = True
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

    if state["difficulty"] == "heavy":
        # O.1 (reply-quality plan, RC-1 fix): heavy/deep-research turns always
        # get a dedicated closing-synthesis pass on the upgraded research
        # tier, run unconditionally after the tool loop resolves (clean stop,
        # budget exhaustion, or iteration cap) -- not just the old "not
        # answered" cases. Before this fix, a clean stop let the cheap
        # orchestrator model's own tool-call-free response serve as the final
        # user-facing answer directly; that's the exact regression the
        # green-hydrogen benchmark caught (`llama-3.3-70b` synthesizing a
        # feasibility report meant for a research-tier model). Mid-loop
        # "thinking" text above (if any) already reached the user live via
        # its own token events (Phase N behavior preserved) -- this call's
        # text is the authoritative closing answer. tools=None so the model
        # can't extend the loop again.
        try:
            final_model_id = resolve_final_model(state["difficulty"], state.get("user_model_id"), resolver, user_id)
        except NoEndpointError:
            final_model_id = model_id

        synthesis_switched_away = False

        async def on_synthesis_model_switch(from_m, to_m):
            nonlocal synthesis_switched_away
            synthesis_switched_away = True
            await on_model_switch(from_m, to_m)

        await adispatch_custom_event("step", {"label": "Composing final answer", "detail": "", "agent": "main"})
        content, _ = await stream_iteration(
            use_tools=False, override_model_id=final_model_id, override_on_model_switch=on_synthesis_model_switch,
        )
        working_messages.append({"role": "assistant", "content": content})

        if synthesis_switched_away:
            await adispatch_custom_event(
                "step",
                {
                    "label": "Synthesis quality may be degraded",
                    "detail": f"{final_model_id} was unavailable; failed over for the final answer",
                    "agent": "main",
                },
            )
    elif not answered:
        # Light (but agentic) turns: unchanged pre-O.1 behavior. A clean stop
        # already produced the real answer above; only budget/iteration-cap
        # exhaustion needs this closing call. Not upgraded to a dedicated
        # synthesis tier -- ROLE_LEVELS["final_light"] ("fast") is now weaker
        # than the orchestrator's own "balanced" tier (Appendix A re-tiering),
        # so forcing every light+agentic turn through an extra, weaker-model
        # call would be a net regression for that path, not a fix.
        await adispatch_custom_event("step", {"label": "Composing final answer", "detail": "", "agent": "main"})
        content, _ = await stream_iteration(use_tools=False)
        working_messages.append({"role": "assistant", "content": content})

    return {
        "messages": working_messages,
        "tool_log": tool_log,
        "citations": citations,
        "tokens_used": tokens_used,
        "final_answer": full_response,
    }


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

    graph.set_entry_point("classify")
    graph.add_conditional_edges(
        "classify", route_after_classify, {"direct_answer": "direct_answer", "plan": "plan"}
    )
    graph.add_edge("direct_answer", END)
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", END)

    return graph
