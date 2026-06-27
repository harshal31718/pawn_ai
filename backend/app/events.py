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


def error_event(message: str) -> str:
    """A recoverable or terminal error."""
    return f"data: {json.dumps({'type': 'error', 'message': message})}\n\n"


def provider_switch_event(from_provider: str, to_provider: str) -> str:
    """Rate-limit failover: switched from one endpoint to another."""
    return f"data: {json.dumps({'type': 'provider_switch', 'from': from_provider, 'to': to_provider})}\n\n"


def step_event(label: str, detail: str = "") -> str:
    """Agent reasoning step — shown in the trace panel."""
    return f"data: {json.dumps({'type': 'step', 'label': label, 'detail': detail})}\n\n"


def memory_hit_event(summary: str) -> str:
    """A relevant memory chunk retrieved from past conversations."""
    return f"data: {json.dumps({'type': 'memory_hit', 'summary': summary})}\n\n"


def model_call_event(model: str, purpose: str) -> str:
    """An internal model call within the agent (draft, critique, etc.)."""
    return f"data: {json.dumps({'type': 'model_call', 'model': model, 'purpose': purpose})}\n\n"
