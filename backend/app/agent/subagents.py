"""Preset subagents (Phase A / A.7): researcher/summarizer/coder.

Each is exposed to the main orchestrator as a `delegate_<name>(task: str)`
tool (see `delegate_tool_specs`). Delegation is **strictly sequential** —
`run_subagent` is awaited inline inside the parent's `execute_node` tool-call
loop (`agent/graph.py`). No `create_task`, no parallelism, ever (locked
product decision #6). Each subagent runs its own bounded native-tool-calling
loop (`SUBAGENT_MAX_ITERATIONS = 5`) and shares the parent's single
`AGENT_MAX_TOKENS` counter via the `tokens_used` in/out value.

Subagents get NO `delegate_*` tools of their own — max depth 1, structurally
guaranteed by the fact that `SUBAGENTS[...].tools_fn` never returns
`delegate_tool_specs()`.
"""

import json
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from langchain_core.callbacks import adispatch_custom_event

from app.agent.oai_tools import extract_citations, to_oai_tool
from app.agent.tools.base import ToolContext, ToolSpec
from app.agent.tools.execute import run_tool
from app.agent.tools.fetch_url import FETCH_URL_TOOL
from app.agent.tools.web_search import WEB_SEARCH_TOOL
from app.constants import AGENT_MAX_TOKENS, ROLE_LEVELS, SUBAGENT_MAX_ITERATIONS
from app.core import key_store, normalize
from app.exceptions import NoEndpointError, ProviderError


@dataclass
class SubagentPreset:
    name: str
    description: str  # shown to the orchestrator model as the delegate_<name> tool description
    system_prompt: str
    tools_fn: Callable[[ToolContext], List[ToolSpec]]
    role_level: str


def _researcher_tools(ctx: ToolContext) -> List[ToolSpec]:
    """fetch_url is always available; web_search only when a search key is
    configured -- same gating rule the main agent's tool registry uses (A.3)."""
    tools = [FETCH_URL_TOOL]
    if key_store.has_search_key(ctx.user_id):
        tools.append(WEB_SEARCH_TOOL)
    return tools


def _no_tools(ctx: ToolContext) -> List[ToolSpec]:
    return []


DELEGATE_TASK_PARAMETERS = {
    "type": "object",
    "properties": {
        "task": {"type": "string", "description": "The concrete task to delegate to this subagent."},
    },
    "required": ["task"],
}


SUBAGENTS: Dict[str, SubagentPreset] = {
    "researcher": SubagentPreset(
        name="researcher",
        description=(
            "Delegates a research task to a subagent that can search the web and "
            "fetch pages (web_search/fetch_url), returning a concise, sourced "
            "digest of what it found."
        ),
        system_prompt=(
            "You are a research subagent. Gather facts relevant to the task using "
            "your available tools, and return a concise digest of your findings "
            "with sources. Do not speculate beyond what you found."
        ),
        tools_fn=_researcher_tools,
        role_level=ROLE_LEVELS["subagent_researcher"],
    ),
    "summarizer": SubagentPreset(
        name="summarizer",
        description=(
            "Delegates a summarization task to a subagent that condenses the "
            "given text into a clear, concise summary. It has no tools -- pass "
            "it the full text to summarize in the task."
        ),
        system_prompt=(
            "You are a summarizing subagent. Condense the text given to you into "
            "a clear, concise summary. You have no tools -- work only from the "
            "text in the task."
        ),
        tools_fn=_no_tools,
        role_level=ROLE_LEVELS["subagent_summarizer"],
    ),
    "coder": SubagentPreset(
        name="coder",
        description=(
            "Delegates a coding task to a subagent that writes or reviews code. "
            "It has no tools -- give it the full context it needs in the task."
        ),
        system_prompt=(
            "You are a coding subagent. Write or review code exactly as "
            "instructed, explaining your reasoning briefly. You have no tools -- "
            "work only from the task description given."
        ),
        tools_fn=_no_tools,
        role_level=ROLE_LEVELS["subagent_coder"],
    ),
}

DELEGATE_PREFIX = "delegate_"


async def _on_provider_switch_events(from_p: str, to_p: str) -> None:
    """Dispatches a provider_switch custom event for failovers inside a
    subagent's own chat_complete calls (A.9-7 gap fix). Defined here (not
    imported from graph.py) to avoid a graph<->subagents circular import."""
    await adispatch_custom_event("provider_switch", {"from_provider": from_p, "to_provider": to_p})


def delegate_tool_specs() -> List[dict]:
    """OAI-format tool schemas for the three delegate_<name> tools, to be
    appended to the orchestrator's own tool_specs list. These never go
    through the generic `run_tool` dispatch -- `execute_node` special-cases
    the `delegate_` prefix and calls `run_subagent` directly, since a
    subagent's result needs to feed back tokens_used/tool_log/citations to
    the parent request, not just a plain string observation."""
    return [
        {
            "type": "function",
            "function": {
                "name": f"{DELEGATE_PREFIX}{name}",
                "description": preset.description,
                "parameters": DELEGATE_TASK_PARAMETERS,
            },
        }
        for name, preset in SUBAGENTS.items()
    ]


async def run_subagent(name: str, task: str, ctx: ToolContext, tokens_used: int) -> Dict[str, Any]:
    """Runs one preset subagent's own bounded tool loop to completion. Never
    raises -- any failure resolves to a `TOOL_ERROR`-prefixed result string,
    same convention as every other tool observation in the graph.

    Returns {"result": str, "tool_log": [...], "citations": [...], "tokens_used": int}.
    `tool_log`/`citations` entries are tagged `agent: name` so the parent's
    trace can render them nested (A.8). `tokens_used` is the running total
    shared with the parent's AGENT_MAX_TOKENS budget.
    """
    preset = SUBAGENTS.get(name)
    if preset is None:
        return {"result": f"TOOL_ERROR: unknown subagent '{name}'", "tool_log": [], "citations": [], "tokens_used": tokens_used}

    tools = preset.tools_fn(ctx)
    tool_specs = [to_oai_tool(t) for t in tools]
    tools_by_name = {t.name: t for t in tools}

    try:
        model_id = ctx.resolver.pick_model_by_capability(
            preset.role_level, user_id=ctx.user_id, require_tools=bool(tools)
        )
    except NoEndpointError as e:
        return {"result": f"TOOL_ERROR: no model available for {name} subagent: {e}", "tool_log": [], "citations": [], "tokens_used": tokens_used}

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": preset.system_prompt},
        {"role": "user", "content": task},
    ]
    tool_log: List[Dict[str, Any]] = []
    citations: List[Dict[str, str]] = []
    seen_urls = set()
    final_text = None

    for _ in range(SUBAGENT_MAX_ITERATIONS):
        if tokens_used >= AGENT_MAX_TOKENS:
            break

        try:
            result = await normalize.chat_complete(
                model_id, messages, ctx.resolver, ctx.rate_limiter, user_id=ctx.user_id, tools=tool_specs,
                on_provider_switch=_on_provider_switch_events,
                on_model_switch=_on_provider_switch_events,
            )
        except (ProviderError, NoEndpointError) as e:
            print(f"Subagent {name} chat_complete failed (upstream): {e}", file=sys.stderr)
            break
        except Exception as e:
            print(f"Subagent {name} chat_complete failed (unexpected): {e}", file=sys.stderr)
            break

        tokens_used += (result.get("usage") or {}).get("total_tokens", 0) or 0
        tool_calls = result.get("tool_calls")
        content = result.get("content") or ""

        if not tool_calls:
            final_text = content
            break

        messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})

        for call in tool_calls:
            fn = call.get("function", {}) or {}
            tname = fn.get("name", "")
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                args = {}

            await adispatch_custom_event("step", {"label": f"Calling {tname}", "detail": json.dumps(args), "agent": name})

            start = time.monotonic()
            if tname.startswith(DELEGATE_PREFIX):
                # Depth guard (max depth 1, locked): a subagent must never be
                # able to delegate further, even if a future preset's tools_fn
                # were changed to expose a delegate-shaped tool by mistake.
                observation = "TOOL_ERROR: subagents cannot delegate further (max depth 1)"
            else:
                spec = tools_by_name.get(tname)
                if spec is None:
                    observation = f"TOOL_ERROR: unknown tool '{tname}'"
                else:
                    observation = await run_tool(spec, args, ctx)
            elapsed_ms = int((time.monotonic() - start) * 1000)

            tool_log.append({"name": tname, "args": args, "observation": observation, "elapsed_ms": elapsed_ms, "agent": name})

            for citation in extract_citations(tname, args, observation):
                if citation["url"] not in seen_urls:
                    seen_urls.add(citation["url"])
                    citations.append(citation)
                    await adispatch_custom_event("citation", citation)

            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": observation})

    if final_text is None:
        if tool_log:
            digest = "; ".join(f"{t['name']}: {t['observation'][:200]}" for t in tool_log)
            final_text = f"({name} subagent did not conclude within its budget; partial findings: {digest})"
        else:
            final_text = f"({name} subagent did not produce a result within its budget.)"

    return {"result": final_text, "tool_log": tool_log, "citations": citations, "tokens_used": tokens_used}
