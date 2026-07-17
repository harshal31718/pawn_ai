"""
Typed SSE event builders.

Every SSE event the server emits is created here.
Never write a raw `data: ...` string in a route or agent node.
Format: `data: <json>\n\n`
"""
import json


def token_event(delta: str) -> str:
    """A single streamed token from the LLM."""
    return f"data: {json.dumps({'type': 'token', 'delta': delta})}\n\n"


def done_event(via_provider: str = "", via_endpoint_id: str = "") -> str:
    """Stream finished successfully."""
    return f"data: {json.dumps({'type': 'done', 'via_provider': via_provider, 'via_endpoint_id': via_endpoint_id})}\n\n"


def error_event(message: str, code: str = "") -> str:
    """A recoverable or terminal error."""
    payload: dict = {"type": "error", "message": message}
    if code:
        payload["code"] = code
    return f"data: {json.dumps(payload)}\n\n"


def rate_limit_event(retry_after: int, provider: str = "") -> str:
    """All endpoints rate-limited — client should show a countdown timer."""
    return f"data: {json.dumps({'type': 'error', 'code': 'rate_limit', 'message': f'Rate limited by {provider}' if provider else 'Rate limited', 'retry_after': retry_after})}\n\n"


def provider_switch_event(from_provider: str, to_provider: str) -> str:
    """Rate-limit failover: switched from one endpoint to another."""
    return f"data: {json.dumps({'type': 'provider_switch', 'from': from_provider, 'to': to_provider})}\n\n"


def step_event(label: str, detail: str = "", agent: str = "main") -> str:
    """Agent reasoning step — shown in the trace panel. `agent` is "main" for
    the orchestrator, or a subagent name (Phase A / A.7) for nested steps."""
    return f"data: {json.dumps({'type': 'step', 'label': label, 'detail': detail, 'agent': agent})}\n\n"


def memory_hit_event(summary: str, scope: str = "", source_conv_id: str = "") -> str:
    """A relevant memory chunk retrieved from the active chat's or project's
    scoped RAG. `scope` is 'chat' or 'project'; `source_conv_id` is which chat
    actually wrote the chunk (most useful for project hits, where it may
    differ from the chat the user is currently in)."""
    payload: dict = {"type": "memory_hit", "summary": summary}
    if scope:
        payload["scope"] = scope
    if source_conv_id:
        payload["source_conv_id"] = source_conv_id
    return f"data: {json.dumps(payload)}\n\n"


def model_call_event(model: str, purpose: str) -> str:
    """An internal model call within the agent (draft, critique, etc.)."""
    return f"data: {json.dumps({'type': 'model_call', 'model': model, 'purpose': purpose})}\n\n"


def citation_event(url: str, title: str) -> str:
    """A source the agent actually used (web_search/fetch_url result, or a URL
    present in the final answer). One per distinct URL — emitted by the
    execute loop (A.6)."""
    return f"data: {json.dumps({'type': 'citation', 'url': url, 'title': title})}\n\n"


def tool_result_event(name: str, observation: str, agent: str = "main") -> str:
    """F-11 follow-up: a tool call's real result, live -- `step_event` only
    ever carries the call's *args* (emitted before the call runs); until this
    event, `observation` was never sent over SSE at all, only attached to the
    persisted message after the whole turn finishes. That meant anything
    keyed off a tool's observation (e.g. ImageJobChip's job id) could never
    appear during a live stream, only after a later reload. Emitted right
    after the tool call resolves, same `agent` tag as its `step` event so the
    client can match them up."""
    return f"data: {json.dumps({'type': 'tool_result', 'name': name, 'observation': observation, 'agent': agent})}\n\n"
