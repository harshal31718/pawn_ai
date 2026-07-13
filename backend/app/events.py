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


def step_event(label: str, detail: str = "") -> str:
    """Agent reasoning step — shown in the trace panel."""
    return f"data: {json.dumps({'type': 'step', 'label': label, 'detail': detail})}\n\n"


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
