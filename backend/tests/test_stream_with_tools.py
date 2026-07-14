"""Tests for the streaming+tools path (Phase N — llm_core.stream_chat_with_tools
+ normalize.chat_stream_with_tools/_stream_one_model_with_tools), the primitive
the merged execute_node tool loop depends on entirely. Covers the OAI
streaming tool_calls delta-accumulation contract (index-keyed; id/type/name
assigned, not concatenated; arguments concatenated) and the two-level
failover contract (same as chat_stream/_stream_one_model: no retry once a
content token has reached the user for a given call).
"""

import json as _json

import pytest
from unittest.mock import patch

from app.core import llm_core, normalize
from app.core.rate_limiter import EndpointRateLimiter
from app.exceptions import ProviderError
from app.registry.loader import load_registry
from app.resolver.resolver import Resolver


def _sse(obj: dict) -> str:
    return f"data: {_json.dumps(obj)}"


def _keys(*allowed):
    allowed_set = set(allowed)

    def fake_get_key(user_id, provider):
        return "KEY" if provider in allowed_set else None

    return patch("app.core.key_store.get_key", side_effect=fake_get_key)


class _FakeStreamCM:
    def __init__(self, lines: list[str], status_code: int = 200):
        self._lines = lines
        self.status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self) -> bytes:
        return b"upstream error body"


class _FakeClient:
    def __init__(self, lines: list[str], status_code: int = 200):
        self._lines = lines
        self._status_code = status_code
        self.last_call: dict | None = None

    def stream(self, method, url, json=None, headers=None):
        self.last_call = {"method": method, "url": url, "json": json, "headers": headers}
        return _FakeStreamCM(self._lines, self._status_code)


def _patched_client(lines: list[str], status_code: int = 200):
    return patch.object(llm_core, "_get_client", return_value=_FakeClient(lines, status_code))


# ── llm_core.stream_chat_with_tools ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_chat_with_tools_yields_content_deltas_then_done():
    lines = [
        _sse({"choices": [{"delta": {"content": "Hel"}, "finish_reason": None}]}),
        _sse({"choices": [{"delta": {"content": "lo"}, "finish_reason": None}]}),
        _sse({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
        "data: [DONE]",
    ]
    events = []
    with _patched_client(lines):
        async for event in llm_core.stream_chat_with_tools(
            "https://example.com", "some-model", [{"role": "user", "content": "hi"}], {"Authorization": "Bearer x"},
        ):
            events.append(event)

    content_events = [e for e in events if e["type"] == "content"]
    assert [e["delta"] for e in content_events] == ["Hel", "lo"]
    assert events[-1] == {"type": "done", "tool_calls": None, "finish_reason": "stop", "usage": None}


@pytest.mark.asyncio
async def test_stream_chat_with_tools_forwards_tools_and_stream_options():
    lines = [_sse({"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}), "data: [DONE]"]
    client = _FakeClient(lines)
    with patch.object(llm_core, "_get_client", return_value=client):
        async for _ in llm_core.stream_chat_with_tools(
            "https://example.com", "some-model", [{"role": "user", "content": "hi"}], {"Authorization": "Bearer x"},
            tools=[{"type": "function", "function": {"name": "calculator"}}], tool_choice="auto",
        ):
            pass

    payload = client.last_call["json"]
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}
    assert payload["tools"]
    assert payload["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_stream_chat_with_tools_accumulates_arguments_split_across_chunks():
    lines = [
        _sse({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_1", "type": "function", "function": {"name": "calculator", "arguments": ""}},
        ]}, "finish_reason": None}]}),
        _sse({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '{"expr'}},
        ]}, "finish_reason": None}]}),
        _sse({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": 'ession": "2+2"}'}},
        ]}, "finish_reason": None}]}),
        _sse({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}),
        "data: [DONE]",
    ]
    events = []
    with _patched_client(lines):
        async for event in llm_core.stream_chat_with_tools(
            "https://example.com", "some-model", [{"role": "user", "content": "hi"}], {"Authorization": "Bearer x"},
            tools=[{"type": "function", "function": {"name": "calculator"}}],
        ):
            events.append(event)

    done = events[-1]
    assert done["finish_reason"] == "tool_calls"
    assert done["tool_calls"] == [
        {"id": "call_1", "type": "function", "function": {"name": "calculator", "arguments": '{"expression": "2+2"}'}}
    ]


@pytest.mark.asyncio
async def test_stream_chat_with_tools_id_type_name_assigned_not_concatenated():
    """A non-compliant provider resending id/type/name on a later chunk must
    NOT corrupt the accumulated value -- only `arguments` concatenates."""
    lines = [
        _sse({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_1", "type": "function", "function": {"name": "calculator", "arguments": '{"a":'}},
        ]}, "finish_reason": None}]}),
        _sse({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_1", "type": "function", "function": {"name": "calculator", "arguments": '1}'}},
        ]}, "finish_reason": None}]}),
        _sse({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}),
        "data: [DONE]",
    ]
    events = []
    with _patched_client(lines):
        async for event in llm_core.stream_chat_with_tools(
            "https://example.com", "some-model", [{"role": "user", "content": "hi"}], {"Authorization": "Bearer x"},
        ):
            events.append(event)

    tool_call = events[-1]["tool_calls"][0]
    assert tool_call["id"] == "call_1"
    assert tool_call["function"]["name"] == "calculator"  # not "calculatorcalculator"
    assert tool_call["function"]["arguments"] == '{"a":1}'  # arguments DID concatenate


@pytest.mark.asyncio
async def test_stream_chat_with_tools_multiple_tool_calls_interleaved_by_index():
    lines = [
        _sse({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "call_1", "type": "function", "function": {"name": "calculator", "arguments": ""}},
        ]}, "finish_reason": None}]}),
        _sse({"choices": [{"delta": {"tool_calls": [
            {"index": 1, "id": "call_2", "type": "function", "function": {"name": "get_datetime", "arguments": ""}},
        ]}, "finish_reason": None}]}),
        _sse({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": "{}"}},
        ]}, "finish_reason": None}]}),
        _sse({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}),
        "data: [DONE]",
    ]
    events = []
    with _patched_client(lines):
        async for event in llm_core.stream_chat_with_tools(
            "https://example.com", "some-model", [{"role": "user", "content": "hi"}], {"Authorization": "Bearer x"},
        ):
            events.append(event)

    tool_calls = events[-1]["tool_calls"]
    assert [t["id"] for t in tool_calls] == ["call_1", "call_2"]  # ordered by index, not arrival
    assert [t["function"]["name"] for t in tool_calls] == ["calculator", "get_datetime"]
    assert tool_calls[0]["function"]["arguments"] == "{}"


@pytest.mark.asyncio
async def test_stream_chat_with_tools_captures_usage_from_usage_only_chunk():
    """Some providers send a final usage-only chunk with an empty `choices`
    array (the OAI stream_options.include_usage shape) -- must not be
    skipped as a no-op before the usage is captured."""
    lines = [
        _sse({"choices": [{"delta": {"content": "ok"}, "finish_reason": None}]}),
        _sse({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
        _sse({"choices": [], "usage": {"total_tokens": 42}}),
        "data: [DONE]",
    ]
    events = []
    with _patched_client(lines):
        async for event in llm_core.stream_chat_with_tools(
            "https://example.com", "some-model", [{"role": "user", "content": "hi"}], {"Authorization": "Bearer x"},
        ):
            events.append(event)

    assert events[-1]["usage"] == {"total_tokens": 42}


@pytest.mark.asyncio
async def test_stream_chat_with_tools_raises_on_429():
    with _patched_client([], status_code=429):
        with pytest.raises(ProviderError) as exc:
            async for _ in llm_core.stream_chat_with_tools(
                "https://example.com", "some-model", [{"role": "user", "content": "hi"}], {"Authorization": "Bearer x"},
            ):
                pass
    assert exc.value.kind == "rate_limit"


# ── normalize.chat_stream_with_tools / _stream_one_model_with_tools failover ─

@pytest.mark.asyncio
async def test_normalize_chat_stream_with_tools_cross_model_failover_before_content():
    """Endpoint/model exhausted before any content -> falls back to another
    keyed model and completes, mirroring chat_stream's own cross-model test."""
    resolver = Resolver(load_registry(), EndpointRateLimiter())

    async def selective_stream(url, model, messages, headers, tools=None, tool_choice="auto"):
        if "generativelanguage" in url:
            raise ProviderError(kind="rate_limit", message="429 rate limited")
        yield {"type": "content", "delta": "from groq"}
        yield {"type": "done", "tool_calls": None, "finish_reason": "stop", "usage": None}

    with _keys("google", "groq"), patch("app.core.normalize._stream_chat_with_tools_llm", side_effect=selective_stream):
        events = []
        async for event in normalize.chat_stream_with_tools(
            model_id="gemini-2.5-flash-lite",
            messages=[{"role": "user", "content": "hi"}],
            resolver=resolver,
            rate_limiter=resolver._rate_limiter,
            user_id="u",
        ):
            events.append(event)

    assert [e["delta"] for e in events if e["type"] == "content"] == ["from groq"]


@pytest.mark.asyncio
async def test_normalize_chat_stream_with_tools_no_retry_once_content_sent():
    """Once a content token has reached the user for a given call, a
    mid-stream failure must propagate directly -- never retried against a
    different endpoint/model, even when one is available and keyed."""
    resolver = Resolver(load_registry(), EndpointRateLimiter())
    call_count = {"n": 0}

    async def flaky_stream(url, model, messages, headers, tools=None, tool_choice="auto"):
        call_count["n"] += 1
        yield {"type": "content", "delta": "partial"}
        raise ProviderError(kind="upstream_error", message="mid-stream failure")

    with _keys("google", "groq"), patch("app.core.normalize._stream_chat_with_tools_llm", side_effect=flaky_stream):
        with pytest.raises(ProviderError):
            async for _ in normalize.chat_stream_with_tools(
                model_id="gemini-2.5-flash-lite",
                messages=[{"role": "user", "content": "hi"}],
                resolver=resolver,
                rate_limiter=resolver._rate_limiter,
                user_id="u",
            ):
                pass

    assert call_count["n"] == 1  # never tried a second endpoint/model after content was sent


@pytest.mark.asyncio
async def test_normalize_chat_stream_with_tools_passes_through_tool_calls_in_done_event():
    resolver = Resolver(load_registry(), EndpointRateLimiter())

    async def fake_stream(url, model, messages, headers, tools=None, tool_choice="auto"):
        yield {
            "type": "done",
            "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "calculator", "arguments": "{}"}}],
            "finish_reason": "tool_calls",
            "usage": None,
        }

    with _keys("google"), patch("app.core.normalize._stream_chat_with_tools_llm", side_effect=fake_stream):
        events = []
        async for event in normalize.chat_stream_with_tools(
            model_id="gemini-2.5-flash-lite",
            messages=[{"role": "user", "content": "hi"}],
            resolver=resolver,
            rate_limiter=resolver._rate_limiter,
            user_id="u",
            tools=[{"type": "function", "function": {"name": "calculator"}}],
        ):
            events.append(event)

    assert events[-1]["tool_calls"][0]["function"]["name"] == "calculator"
