from typing import TypedDict, Optional, List, Dict, Any
from functools import partial
import asyncio

from langgraph.graph import StateGraph, END
from langchain_core.callbacks import adispatch_custom_event

from app.agent.parser import parse_action
from app.core import normalize
from app.resolver.resolver import Resolver
from app.core.rate_limiter import EndpointRateLimiter

class DummyRateLimiter:
    def can_use(self, endpoint) -> bool: return True
    def record_call(self, endpoint_id, token_count=0): pass
    def record_429(self, endpoint_id, retry_after=60): pass
    def record_connect_failure(self, endpoint_id): pass
    def record_success(self, endpoint_id): pass

class DummyResolver:
    def pick(self, model_id, user_id=None):
        return [("https://api.google.com", "gemini-2.5-flash", {}, "ep-dummy", "google")]
    def pick_by_capability(self, level, visibility="internal"):
        return [("https://api.google.com", "gemini-2.5-flash", {}, "ep-dummy", "google")]
    def pick_model_by_capability(self, level, visibility="internal"):
        return "gemini-2.5-flash"

class AgentState(TypedDict):
    conversation_id: str
    user_id: str
    history: List[Dict[str, Any]]
    retrieved_memory: List[str]
    scratchpad: List[Dict[str, Any]]
    next_action: Optional[Dict[str, Any]]
    final_answer: Optional[str]
    user_model_id: str
    step_count: int

def build_agent_prompt(
    history: List[Dict[str, Any]],
    memory: List[str],
    scratchpad: List[Dict[str, Any]],
    available_actions: List[str],
    step_count: int
) -> str:
    conv_parts = []
    for msg in history:
        conv_parts.append(f"{msg['role'].upper()}: {msg['content']}")
    conv_str = "\n".join(conv_parts)

    memory_str = "\n".join(f"- {m}" for m in memory) if memory else "No past memory retrieved."

    scratch_parts = []
    for idx, step in enumerate(scratchpad):
        action_type = step.get("action")
        if action_type == "search_memory":
            scratch_parts.append(
                f"STEP {idx+1} ACTION: {action_type}(query='{step.get('query')}')\n"
                f"RESULT: {step.get('result')}"
            )
        elif action_type == "ask_model":
            scratch_parts.append(
                f"STEP {idx+1} ACTION: {action_type}(purpose='{step.get('purpose')}', prompt='{step.get('prompt')}')\n"
                f"RESULT: {step.get('result')}"
            )
    scratch_str = "\n\n".join(scratch_parts) if scratch_parts else "No steps taken yet."

    prompt = f"""You are an AI assistant orchestrating a multi-turn reasoning graph to answer the user's question.
You must respond with exactly ONE valid JSON action object wrapped in your message. Do not output any prose before or after the JSON.

## Conversation History
{conv_str}

## Retrieved Past Memories
{memory_str}

## Scratchpad (Prior Steps Taken This Turn)
{scratch_str}

## Available Actions
Choose exactly one of the following actions to proceed:
1. search_memory: Look up past conversation summaries/memories.
   JSON Format: {{ "action": "search_memory", "query": "<what to search for>" }}
   
2. ask_model: Delegate a subtask (e.g. draft, critique, research) to a model.
   JSON Format: {{ "action": "ask_model", "purpose": "draft|critique|research", "prompt": "<concrete instructions for the model to do>" }}
   
3. final: Conclude and produce the final answer. If you have gathered enough information, choose this action.
   JSON Format: {{ "action": "final", "answer": "<synthesized answer, or leave empty if you want the main model to write it>" }}

Step Constraint: You have used {step_count} of 8 reasoning steps. If step_count is approaching 8, you MUST choose the "final" action.

Choose the next action. Output ONLY the JSON action.
"""
    return prompt.strip()

def build_synthesis_prompt(
    original_question: str,
    memory: List[str],
    scratchpad: List[Dict[str, Any]],
    agent_answer: str = ""
) -> str:
    scratch_parts = []
    for idx, step in enumerate(scratchpad):
        action_type = step.get("action")
        if action_type == "search_memory":
            scratch_parts.append(
                f"Step {idx+1} (Memory Search for '{step.get('query')}'):\n"
                f"{step.get('result')}"
            )
        elif action_type == "ask_model":
            scratch_parts.append(
                f"Step {idx+1} (Model Delegation '{step.get('purpose')}'):\n"
                f"{step.get('result')}"
            )
    scratch_str = "\n\n".join(scratch_parts) if scratch_parts else "None."

    prompt = f"""You are now composing the final response to the user's question.
Use the collected background research and agent steps summarized below to compose a direct, accurate, and comprehensive answer.

## Original User Question
{original_question}

## Collected Research/Context:
{scratch_str}

{f"## Drafted Answer:\n{agent_answer}" if agent_answer else ""}

Based on the research and drafts above, write a comprehensive, final answer to the user. Answer directly, clearly, and concisely.
"""
    return prompt.strip()


# Graph Nodes

async def load_context_node(state: AgentState) -> dict:
    from app.memory.retrieve import retrieve
    
    query = ""
    if state["history"]:
        query = state["history"][-1]["content"]
        
    hits = []
    if query:
        hits = await retrieve(
            query,
            user_id=state.get("user_id"),
            active_conv_id=state["conversation_id"],
            top_k=3,
        )

    for hit in hits:
        await adispatch_custom_event("memory_hit", {"summary": hit["text"]})

    return {
        "retrieved_memory": [h["text"] for h in hits]
    }

async def agent_node(
    state: AgentState,
    resolver: Optional[Resolver] = None,
    rate_limiter: Optional[EndpointRateLimiter] = None
) -> dict:
    if resolver is None or rate_limiter is None:
        resolver = resolver or DummyResolver()
        rate_limiter = rate_limiter or DummyRateLimiter()

    step_count = state["step_count"]
    if step_count >= 8:
        last_result = state["scratchpad"][-1].get("result", "") if state["scratchpad"] else "Step limit exceeded."
        return {
            "next_action": {"action": "final", "answer": last_result},
            "step_count": step_count + 1
        }
        
    prompt = build_agent_prompt(
        history=state["history"],
        memory=state["retrieved_memory"],
        scratchpad=state["scratchpad"],
        available_actions=["search_memory", "ask_model", "final"],
        step_count=step_count
    )
    
    await adispatch_custom_event("step", {"label": "Thinking", "detail": f"step {step_count + 1}"})
    
    model_id = resolver.pick_model_by_capability("fast")
    
    async def on_switch(from_p, to_p):
        await adispatch_custom_event("provider_switch", {"from_provider": from_p, "to_provider": to_p})
        
    response = ""
    async for token in normalize.chat_stream(
        model_id=model_id,
        messages=[{"role": "user", "content": prompt}],
        resolver=resolver,
        rate_limiter=rate_limiter,
        on_provider_switch=on_switch,
        user_id=state.get("user_id"),
    ):
        response += token

    action = parse_action(response)
    
    if not isinstance(action, dict) or "action" not in action:
        action = {"action": "final", "answer": response.strip()}
        
    return {
        "next_action": action,
        "step_count": step_count + 1
    }

async def search_memory_node(state: AgentState) -> dict:
    query = state["next_action"]["query"]
    await adispatch_custom_event("step", {"label": "Searching memory", "detail": query})
    
    from app.memory.retrieve import retrieve
    hits = await retrieve(
        query,
        user_id=state.get("user_id"),
        active_conv_id=state["conversation_id"],
        top_k=3,
    )

    for hit in hits:
        await adispatch_custom_event("memory_hit", {"summary": hit["text"]})

    result = "\n".join(h["text"] for h in hits) if hits else "No relevant memory found."
    scratchpad = state["scratchpad"] + [{"action": "search_memory", "query": query, "result": result}]
    
    return {
        "scratchpad": scratchpad,
        "next_action": None
    }

async def ask_model_node(
    state: AgentState,
    resolver: Optional[Resolver] = None,
    rate_limiter: Optional[EndpointRateLimiter] = None
) -> dict:
    if resolver is None or rate_limiter is None:
        resolver = resolver or DummyResolver()
        rate_limiter = rate_limiter or DummyRateLimiter()

    purpose = state["next_action"]["purpose"]
    prompt_text = state["next_action"]["prompt"]
    user_id = state.get("user_id")

    from app.agent.routing import PURPOSE_TO_LEVEL
    level = PURPOSE_TO_LEVEL.get(purpose, "balanced")
    model_id = resolver.pick_model_by_capability(level)

    candidates = resolver.pick(model_id, user_id=user_id)
    active_provider = candidates[0][4] if candidates else "unknown"
    active_provider_model = candidates[0][1] if candidates else "unknown"
    
    await adispatch_custom_event("model_call", {"model": f"{active_provider}:{active_provider_model}", "purpose": purpose})
    await adispatch_custom_event("step", {"label": "Drafting" if purpose == "draft" else "Critiquing", "detail": purpose})
    
    async def on_switch(from_p, to_p):
        await adispatch_custom_event("provider_switch", {"from_provider": from_p, "to_provider": to_p})
        
    response = ""
    async for token in normalize.chat_stream(
        model_id=model_id,
        messages=[{"role": "user", "content": prompt_text}],
        resolver=resolver,
        rate_limiter=rate_limiter,
        on_provider_switch=on_switch,
        user_id=user_id,
    ):
        response += token

    scratchpad = state["scratchpad"] + [{"action": "ask_model", "purpose": purpose, "result": response}]
    return {
        "scratchpad": scratchpad,
        "next_action": None
    }

async def final_node(
    state: AgentState,
    resolver: Optional[Resolver] = None,
    rate_limiter: Optional[EndpointRateLimiter] = None
) -> dict:
    if resolver is None or rate_limiter is None:
        resolver = resolver or DummyResolver()
        rate_limiter = rate_limiter or DummyRateLimiter()

    synthesis_prompt = build_synthesis_prompt(
        original_question=state["history"][-1]["content"],
        memory=state["retrieved_memory"],
        scratchpad=state["scratchpad"],
        agent_answer=state["next_action"].get("answer", "") if state["next_action"] else ""
    )
    
    await adispatch_custom_event("step", {"label": "Composing final answer", "detail": ""})

    user_id = state.get("user_id")
    model_id = state["user_model_id"]
    candidates = resolver.pick(model_id, user_id=user_id)
    initial_provider = candidates[0][4] if candidates else "unknown"
    
    await adispatch_custom_event("final_provider", {"provider": initial_provider})
    
    async def on_switch(from_p, to_p):
        await adispatch_custom_event("provider_switch", {"from_provider": from_p, "to_provider": to_p})
        await adispatch_custom_event("final_provider", {"provider": to_p})
        
    full_response = ""
    async for token in normalize.chat_stream(
        model_id=model_id,
        messages=state["history"] + [{"role": "user", "content": synthesis_prompt}],
        resolver=resolver,
        rate_limiter=rate_limiter,
        on_provider_switch=on_switch,
        user_id=user_id,
    ):
        full_response += token
        await adispatch_custom_event("token", {"delta": token})
        
    return {
        "final_answer": full_response
    }


def route_action(state: AgentState) -> str:
    action = state.get("next_action")
    if not action or not isinstance(action, dict):
        return "agent"
    act_type = action.get("action")
    if act_type in ["search_memory", "ask_model", "final"]:
        return act_type
    return "agent"


def build_agent_graph(
    resolver: Optional[Resolver] = None,
    rate_limiter: Optional[EndpointRateLimiter] = None
) -> StateGraph:
    if resolver is None or rate_limiter is None:
        resolver = resolver or DummyResolver()
        rate_limiter = rate_limiter or DummyRateLimiter()

    graph = StateGraph(AgentState)
    
    graph.add_node("load_context", load_context_node)
    graph.add_node("agent", partial(agent_node, resolver=resolver, rate_limiter=rate_limiter))
    graph.add_node("search_memory", search_memory_node)
    graph.add_node("ask_model", partial(ask_model_node, resolver=resolver, rate_limiter=rate_limiter))
    graph.add_node("final", partial(final_node, resolver=resolver, rate_limiter=rate_limiter))
    
    graph.set_entry_point("load_context")
    graph.add_edge("load_context", "agent")
    
    graph.add_conditional_edges(
        "agent",
        route_action,
        {
            "search_memory": "search_memory",
            "ask_model": "ask_model",
            "final": "final",
            "agent": "agent"
        }
    )
    
    graph.add_edge("search_memory", "agent")
    graph.add_edge("ask_model", "agent")
    graph.add_edge("final", END)
    
    return graph
