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
    tool_choice: str = "auto",
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
