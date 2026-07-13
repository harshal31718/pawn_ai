"""Cross-model failover in normalize.chat_stream.

When every keyed provider for the selected model is rate-limited (before any token),
the stream should fall back to another model the user has a key for and complete.
"""

import pytest
from unittest.mock import patch

from app.core import normalize
from app.resolver.resolver import Resolver
from app.registry.loader import load_registry
from app.core.rate_limiter import EndpointRateLimiter
from app.exceptions import ProviderError


def _keys(*allowed):
    allowed_set = set(allowed)

    def fake_get_key(user_id, provider):
        return "KEY" if provider in allowed_set else None

    return patch("app.core.key_store.get_key", side_effect=fake_get_key)


@pytest.mark.asyncio
async def test_cross_model_fallback_completes_on_groq():
    """User has google + groq. The selected Google model is rate-limited on every
    keyed endpoint → the reply completes on a Groq-served model, and on_model_switch
    fires for the switch."""
    resolver = Resolver(load_registry(), EndpointRateLimiter())

    async def selective_stream(url, model, messages, headers):
        if "generativelanguage" in url:
            raise ProviderError(kind="rate_limit", message="429 rate limited")
        yield "ok"

    switches: list[tuple[str, str]] = []

    async def on_model_switch(frm, to):
        switches.append((frm, to))

    tokens: list[str] = []
    with _keys("google", "groq"), patch("app.core.normalize.stream_llm", side_effect=selective_stream):
        async for tok in normalize.chat_stream(
            model_id="gemini-2.5-flash-lite",
            messages=[{"role": "user", "content": "hi"}],
            resolver=resolver,
            rate_limiter=resolver._rate_limiter,
            user_id="u",
            on_model_switch=on_model_switch,
        ):
            tokens.append(tok)

    assert tokens == ["ok"]                      # reply completed via the fallback model
    assert any(to == "llama-3.3-70b" for _, to in switches)  # switched to the groq model


@pytest.mark.asyncio
async def test_no_fallback_when_user_only_has_the_rate_limited_provider():
    """User has only google; the only Google model is rate-limited → no usable
    fallback, so a ProviderError(rate_limit) surfaces."""
    resolver = Resolver(load_registry(), EndpointRateLimiter())

    async def always_rate_limited(url, model, messages, headers):
        raise ProviderError(kind="rate_limit", message="429")
        yield  # pragma: no cover

    with _keys("google"), patch("app.core.normalize.stream_llm", side_effect=always_rate_limited):
        with pytest.raises(ProviderError) as exc:
            async for _ in normalize.chat_stream(
                model_id="gemini-2.5-flash-lite",
                messages=[{"role": "user", "content": "hi"}],
                resolver=resolver,
                rate_limiter=resolver._rate_limiter,
                user_id="u",
            ):
                pass
        assert exc.value.kind == "rate_limit"
