import json
import urllib.parse
from typing import AsyncGenerator

import httpx

from app.exceptions import ProviderError

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
    return _client


def _detect_provider(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower()
    if "anthropic" in host:
        return "anthropic"
    return "openai_compatible"


def _provider_headers(provider: str, api_key: str | None, url: str) -> dict[str, str]:
    if provider == "anthropic":
        return {
            "x-api-key": api_key or "",
            "anthropic-version": "2023-06-01",
        }
    return {"Authorization": f"Bearer {api_key or ''}".strip()}


def _format_upstream_error(status_code: int, body: bytes) -> str:
    if status_code == 401:
        return "API key rejected — check your key in settings"
    if status_code == 429:
        return "Rate limit reached — try again shortly"
    if status_code >= 500:
        return f"Provider returned a server error ({status_code})"
    return f"Provider error ({status_code})"


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def chat_complete(
    url: str,
    model: str,
    messages: list[dict],
    headers: dict[str, str],
    tools: list[dict] | None = None,
    tool_choice: str | dict = "auto",
) -> dict:
    """Non-streaming completion. Returns the full first choice's message dict
    ({"role", "content", "tool_calls"} — shape passed through as-is from the
    provider). Same provider wire format as stream_llm; used for agent-internal
    calls (plan, tool decisions), never for the final user-facing streamed answer."""
    payload: dict = {"model": model, "messages": messages, "stream": False}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice
    resp = await _get_client().post(f"{url}/chat/completions", json=payload, headers=headers)
    if resp.status_code >= 400:
        body = resp.content
        raise ProviderError(
            kind="rate_limit" if resp.status_code == 429 else "upstream_error",
            message=_format_upstream_error(resp.status_code, body),
        )
    data = resp.json()
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise ProviderError(kind="upstream_error", message="Provider returned an unexpected response shape")
    # Token usage isn't part of the OAI message shape but agent-internal callers
    # (A.6's execute loop) need it to enforce AGENT_MAX_TOKENS -- attached as an
    # extra key rather than changing the return shape (non-breaking: existing
    # callers only ever read message["content"]/["tool_calls"]).
    message["usage"] = data.get("usage")
    return message


async def stream_llm(
    url: str, model: str, messages: list[dict[str, str]], headers: dict[str, str]
) -> AsyncGenerator[str, None]:
    payload = {"model": model, "messages": messages, "stream": True}
    async with _get_client().stream(
        "POST", f"{url}/chat/completions", json=payload, headers=headers
    ) as resp:
        if resp.status_code >= 400:
            body = await resp.aread()
            raise ProviderError(
                kind="rate_limit" if resp.status_code == 429 else "upstream_error",
                message=_format_upstream_error(resp.status_code, body),
            )
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                return
            try:
                chunk = json.loads(data)
                delta = chunk["choices"][0]["delta"].get("content", "")
                if delta:
                    yield delta
            except (json.JSONDecodeError, KeyError, IndexError):
                continue


async def stream_chat_with_tools(
    url: str,
    model: str,
    messages: list[dict],
    headers: dict[str, str],
    tools: list[dict] | None = None,
    tool_choice: str | dict = "auto",
) -> AsyncGenerator[dict, None]:
    """Streaming completion WITH tool-calling support in a single request
    (stream=True + tools=[...]) -- lets one call both stream the answer live
    and receive tool_calls, unlike chat_complete (tools, no stream) and
    stream_llm (stream, no tools) above. Yields {"type": "content", "delta":
    str} per content token as it arrives, then a final {"type": "done",
    "tool_calls": [...] | None, "finish_reason": str}. Also attaches a
    best-effort "usage" key to the done event when the provider honors the
    OAI stream_options.include_usage flag below (None otherwise) -- same
    non-breaking extra-key pattern chat_complete already uses for usage.

    Tool-call deltas arrive split across many chunks, keyed by `index`: id/
    type/function.name are each sent whole in the first chunk for that index
    (assigned, not concatenated -- a provider that resent them per-chunk
    would otherwise corrupt the value), while function.arguments arrives as
    successive partial-JSON-string fragments that must be concatenated and
    are never parsed here (the caller parses the fully-accumulated string).
    """
    payload: dict = {
        "model": model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice

    tool_calls: dict[int, dict] = {}
    finish_reason = ""
    usage: dict | None = None

    async with _get_client().stream(
        "POST", f"{url}/chat/completions", json=payload, headers=headers
    ) as resp:
        if resp.status_code >= 400:
            body = await resp.aread()
            raise ProviderError(
                kind="rate_limit" if resp.status_code == 429 else "upstream_error",
                message=_format_upstream_error(resp.status_code, body),
            )
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue

            if chunk.get("usage"):
                usage = chunk["usage"]

            choices = chunk.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            delta = choice.get("delta") or {}
            reason = choice.get("finish_reason")
            if reason:
                finish_reason = reason

            content = delta.get("content")
            if content:
                yield {"type": "content", "delta": content}

            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                slot = tool_calls.setdefault(
                    idx, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                )
                if tc.get("id"):
                    slot["id"] = tc["id"]
                if tc.get("type"):
                    slot["type"] = tc["type"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["function"]["name"] = fn["name"]
                if fn.get("arguments"):
                    slot["function"]["arguments"] += fn["arguments"]

    ordered_calls = [tool_calls[i] for i in sorted(tool_calls)] if tool_calls else None
    yield {"type": "done", "tool_calls": ordered_calls, "finish_reason": finish_reason, "usage": usage}
