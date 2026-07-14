"""Tests for the non-streaming chat_complete path (llm_core + normalize).

chat_complete is agent-internal (plan/tool-decision calls) — never the final
user-facing streamed answer. Same provider wire format / failover as chat_stream.
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.core import llm_core, normalize
from app.resolver.resolver import Resolver
from app.registry.loader import load_registry
from app.core.rate_limiter import EndpointRateLimiter
from app.exceptions import ProviderError


def _keys(*allowed):
    allowed_set = set(allowed)

    def fake_get_key(user_id, provider):
        return "KEY" if provider in allowed_set else None

    return patch("app.core.key_store.get_key", side_effect=fake_get_key)


def _mock_response(status_code=200, json_body=None, content=b""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    if json_body is not None:
        resp.json.return_value = json_body
    return resp


# ── llm_core.chat_complete ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_llm_core_chat_complete_parses_tool_calls():
    tool_calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "calculator", "arguments": '{"expression": "2+2"}'},
        }
    ]
    body = {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": tool_calls}}]}
    resp = _mock_response(200, body)

    with patch.object(llm_core, "_get_client") as get_client:
        get_client.return_value.post = AsyncMock(return_value=resp)
        message = await llm_core.chat_complete(
            "https://example.com", "some-model", [{"role": "user", "content": "hi"}],
            {"Authorization": "Bearer x"}, tools=[{"type": "function", "function": {"name": "calculator"}}],
        )

    assert message["tool_calls"] == tool_calls
    # tools/tool_choice were forwarded in the request payload
    sent_kwargs = get_client.return_value.post.call_args.kwargs
    assert sent_kwargs["json"]["tools"]
    assert sent_kwargs["json"]["tool_choice"] == "auto"
    assert sent_kwargs["json"]["stream"] is False


@pytest.mark.asyncio
async def test_llm_core_chat_complete_no_tools_passthrough():
    body = {"choices": [{"message": {"role": "assistant", "content": "hello there"}}]}
    resp = _mock_response(200, body)

    with patch.object(llm_core, "_get_client") as get_client:
        get_client.return_value.post = AsyncMock(return_value=resp)
        message = await llm_core.chat_complete(
            "https://example.com", "some-model", [{"role": "user", "content": "hi"}],
            {"Authorization": "Bearer x"},
        )

    assert message["content"] == "hello there"
    sent_kwargs = get_client.return_value.post.call_args.kwargs
    assert "tools" not in sent_kwargs["json"]


@pytest.mark.asyncio
async def test_llm_core_chat_complete_raises_clear_error_on_malformed_response():
    """A 200 response with an unexpected shape (missing 'choices') surfaces a clear
    ProviderError instead of a raw KeyError."""
    resp = _mock_response(200, {"unexpected": "shape"})

    with patch.object(llm_core, "_get_client") as get_client:
        get_client.return_value.post = AsyncMock(return_value=resp)
        with pytest.raises(ProviderError) as exc:
            await llm_core.chat_complete(
                "https://example.com", "some-model", [{"role": "user", "content": "hi"}],
                {"Authorization": "Bearer x"},
            )
    assert exc.value.kind == "upstream_error"


@pytest.mark.asyncio
async def test_llm_core_chat_complete_raises_on_429():
    resp = _mock_response(429, content=b"rate limited")

    with patch.object(llm_core, "_get_client") as get_client:
        get_client.return_value.post = AsyncMock(return_value=resp)
        with pytest.raises(ProviderError) as exc:
            await llm_core.chat_complete(
                "https://example.com", "some-model", [{"role": "user", "content": "hi"}],
                {"Authorization": "Bearer x"},
            )
    assert exc.value.kind == "rate_limit"


# ── normalize.chat_complete failover ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_normalize_chat_complete_returns_message():
    resolver = Resolver(load_registry(), EndpointRateLimiter())

    async def fake_complete(url, model, messages, headers, tools=None, tool_choice="auto"):
        return {"role": "assistant", "content": "ok", "tool_calls": None}

    with _keys("google"), patch("app.core.normalize._chat_complete_llm", side_effect=fake_complete):
        message = await normalize.chat_complete(
            model_id="gemini-2.5-flash-lite",
            messages=[{"role": "user", "content": "hi"}],
            resolver=resolver,
            rate_limiter=resolver._rate_limiter,
            user_id="u",
        )

    assert message["content"] == "ok"


@pytest.mark.asyncio
async def test_normalize_chat_complete_fails_over_on_429():
    """Endpoint-level failover: the Google model is rate-limited on every keyed
    endpoint, so chat_complete falls back to a Groq-served model."""
    resolver = Resolver(load_registry(), EndpointRateLimiter())

    async def selective_complete(url, model, messages, headers, tools=None, tool_choice="auto"):
        if "generativelanguage" in url:
            raise ProviderError(kind="rate_limit", message="429 rate limited")
        return {"role": "assistant", "content": "from groq", "tool_calls": None}

    with _keys("google", "groq"), patch("app.core.normalize._chat_complete_llm", side_effect=selective_complete):
        message = await normalize.chat_complete(
            model_id="gemini-2.5-flash-lite",
            messages=[{"role": "user", "content": "hi"}],
            resolver=resolver,
            rate_limiter=resolver._rate_limiter,
            user_id="u",
        )

    assert message["content"] == "from groq"


@pytest.mark.asyncio
async def test_normalize_chat_complete_fires_failover_callbacks():
    """A.9-7 gap fix: chat_complete now accepts on_provider_switch /
    on_model_switch (sync or async) and fires them on failover, mirroring
    chat_stream — so in-loop agent failovers can emit provider_switch SSE
    events instead of happening silently."""
    resolver = Resolver(load_registry(), EndpointRateLimiter())

    async def selective_complete(url, model, messages, headers, tools=None, tool_choice="auto"):
        if "generativelanguage" in url:
            raise ProviderError(kind="rate_limit", message="429 rate limited")
        return {"role": "assistant", "content": "from groq", "tool_calls": None}

    switches: list = []

    async def on_switch(frm, to):
        switches.append((frm, to))

    with _keys("google", "groq"), patch("app.core.normalize._chat_complete_llm", side_effect=selective_complete):
        message = await normalize.chat_complete(
            model_id="gemini-2.5-flash-lite",
            messages=[{"role": "user", "content": "hi"}],
            resolver=resolver,
            rate_limiter=resolver._rate_limiter,
            user_id="u",
            on_provider_switch=on_switch,
            on_model_switch=on_switch,
        )

    assert message["content"] == "from groq"
    # At least one switch (endpoint- or model-level) fired on the way to groq.
    assert switches, "expected a failover callback to fire"


@pytest.mark.asyncio
async def test_normalize_chat_complete_callbacks_silent_on_success():
    """No failover -> no callback calls (and omitting them stays valid)."""
    resolver = Resolver(load_registry(), EndpointRateLimiter())

    async def fake_complete(url, model, messages, headers, tools=None, tool_choice="auto"):
        return {"role": "assistant", "content": "ok", "tool_calls": None}

    switches: list = []

    with _keys("google"), patch("app.core.normalize._chat_complete_llm", side_effect=fake_complete):
        message = await normalize.chat_complete(
            model_id="gemini-2.5-flash-lite",
            messages=[{"role": "user", "content": "hi"}],
            resolver=resolver,
            rate_limiter=resolver._rate_limiter,
            user_id="u",
            on_provider_switch=lambda f, t: switches.append((f, t)),
            on_model_switch=lambda f, t: switches.append((f, t)),
        )

    assert message["content"] == "ok"
    assert switches == []


# ── resolver.pick_model_by_capability require_tools filter ─────────────────

def test_require_tools_excludes_models_without_tool_support():
    registry = load_registry()
    # gemini-2.5-flash-lite is the only 'fast' model with a google key; flip its
    # supports_tools flag off in-memory to prove the filter excludes it.
    registry._models["gemini-2.5-flash-lite"].supports_tools = False
    resolver = Resolver(registry, EndpointRateLimiter())

    from app.exceptions import NoEndpointError

    with _keys("google"):
        with pytest.raises(NoEndpointError):
            resolver.pick_model_by_capability("fast", user_id="u", require_tools=True)
        # without the filter, it still resolves
        assert resolver.pick_model_by_capability("fast", user_id="u") == "gemini-2.5-flash-lite"


def test_require_tools_false_is_a_no_op_by_default():
    resolver = Resolver(load_registry(), EndpointRateLimiter())
    with _keys("google"):
        assert resolver.pick_model_by_capability("fast", user_id="u") == "gemini-2.5-flash-lite"
