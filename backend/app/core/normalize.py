"""
normalize.py — Single entry point for all LLM calls.

Public API:
    async def chat_stream(
        model_id: str,
        messages: list,
        resolver: Resolver,
        rate_limiter: EndpointRateLimiter,
        on_provider_switch: Callable[[str, str], None] | None = None,
    ) -> AsyncGenerator[str, None]:

    async def chat_complete(
        model_id: str,
        messages: list,
        resolver: Resolver,
        rate_limiter: EndpointRateLimiter,
        user_id: str | None = None,
        tools: list | None = None,
        tool_choice: str = "auto",
    ) -> dict:

Routes and agent nodes call ONLY these functions.
Never import llm_core.stream_llm / llm_core.chat_complete directly outside of this module.
"""
import httpx
import asyncio
from typing import AsyncGenerator, Callable
from app.resolver.resolver import Resolver
from app.core.rate_limiter import EndpointRateLimiter
from app.exceptions import ProviderError, NoEndpointError
from app.core.llm_core import stream_llm, chat_complete as _chat_complete_llm

class _ModelExhausted(Exception):
    """Internal: a single model produced no tokens and all its endpoints failed.
    Carries the underlying error so chat_stream can re-raise it if no fallback
    model is available."""
    def __init__(self, error: Exception):
        self.error = error


async def _stream_one_model(
    model_id: str,
    messages: list,
    resolver: Resolver,
    rate_limiter: EndpointRateLimiter,
    on_provider_switch: Callable[[str, str], None] | None,
    user_id: str | None,
) -> AsyncGenerator[str, None]:
    """Stream tokens for ONE model, failing over across that model's keyed endpoints
    (priority order). Raises _ModelExhausted if no endpoint produced any token, so the
    caller can try a different model. Once tokens have been yielded, any mid-stream
    error propagates directly (we cannot safely switch model/endpoint mid-response)."""
    candidates = resolver.pick(model_id, user_id=user_id)

    last_error: Exception | None = None
    for i, (url, provider_model_id, headers, endpoint_id, provider) in enumerate(candidates):
        if i > 0 and on_provider_switch:
            prev_provider = candidates[i - 1][4]
            if asyncio.iscoroutinefunction(on_provider_switch):
                await on_provider_switch(prev_provider, provider)
            else:
                on_provider_switch(prev_provider, provider)

        tokens_yielded = 0
        try:
            async for token in stream_llm(url, provider_model_id, messages, headers):
                if tokens_yielded == 0:
                    rate_limiter.record_call(endpoint_id)
                    rate_limiter.record_success(endpoint_id)
                tokens_yielded += 1
                yield token

            if tokens_yielded == 0:
                rate_limiter.record_call(endpoint_id)
                rate_limiter.record_success(endpoint_id)
            return

        except ProviderError as pe:
            last_error = pe
            if tokens_yielded > 0:
                raise pe
            if pe.kind == "rate_limit":
                rate_limiter.record_429(endpoint_id)
            else:
                rate_limiter.record_connect_failure(endpoint_id)

        except (httpx.HTTPError, Exception) as e:
            last_error = e
            if tokens_yielded > 0:
                raise e
            rate_limiter.record_connect_failure(endpoint_id)

    raise _ModelExhausted(last_error or NoEndpointError(f"No available endpoint for model '{model_id}'"))


async def chat_stream(
    model_id: str,
    messages: list,
    resolver: Resolver,
    rate_limiter: EndpointRateLimiter,
    on_provider_switch: Callable[[str, str], None] | None = None,
    user_id: str | None = None,
    on_model_switch: Callable[[str, str], None] | None = None,
) -> AsyncGenerator[str, None]:
    """Stream tokens for the given model_id, with two-level failover:

    1. Endpoint-level: across the chosen model's keyed providers (priority order).
    2. Model-level: if every keyed provider for the model is rate-limited/unavailable
       (before any token is produced), fall back to another usable model the user has
       a key for (see Resolver.fallback_models), firing on_model_switch.

    Args:
        model_id:           Canonical model ID (e.g. "llama-3.3-70b").
        messages:           OAI-format message list [{"role": ..., "content": ...}, ...].
        resolver:           The Resolver instance.
        rate_limiter:       The EndpointRateLimiter instance.
        on_provider_switch: Callback invoked when a rate limit forces a provider switch
                            within the same model.
        user_id:            If given, only the user's BYOK keys are used.
        on_model_switch:    Callback invoked when failover moves to a different model.

    Yields:
        str — individual token strings.

    Raises:
        ProviderError — on any upstream failure (rate limit, auth, network).
        NoEndpointError — if no endpoints are available for any candidate model.
    """
    models = resolver.fallback_models(model_id, user_id=user_id)

    last_error: Exception | None = None
    for i, candidate_model in enumerate(models):
        if i > 0 and on_model_switch:
            prev_model = models[i - 1]
            if asyncio.iscoroutinefunction(on_model_switch):
                await on_model_switch(prev_model, candidate_model)
            else:
                on_model_switch(prev_model, candidate_model)

        try:
            tokens_yielded = 0
            async for token in _stream_one_model(
                candidate_model, messages, resolver, rate_limiter, on_provider_switch, user_id
            ):
                tokens_yielded += 1
                yield token
            return
        except _ModelExhausted as me:
            last_error = me.error
            continue
        except NoEndpointError as ne:
            # No keyed/available endpoint for this candidate — try the next model.
            last_error = ne
            continue
        # Note: a mid-stream error (after tokens) propagates from _stream_one_model
        # and is intentionally NOT caught here — we cannot restart a partial reply.

    if last_error:
        if isinstance(last_error, ProviderError):
            raise last_error
        if isinstance(last_error, NoEndpointError):
            raise last_error
        raise ProviderError(kind="upstream_error", message=str(last_error))
    raise NoEndpointError(f"No available endpoint for model '{model_id}'")


async def _complete_one_model(
    model_id: str,
    messages: list,
    resolver: Resolver,
    rate_limiter: EndpointRateLimiter,
    user_id: str | None,
    tools: list | None,
    tool_choice: str,
) -> dict:
    """Complete against ONE model, failing over across that model's keyed endpoints
    (priority order). Raises _ModelExhausted if every endpoint failed, so the caller
    can try a different model."""
    candidates = resolver.pick(model_id, user_id=user_id)

    last_error: Exception | None = None
    for url, provider_model_id, headers, endpoint_id, provider in candidates:
        try:
            message = await _chat_complete_llm(
                url, provider_model_id, messages, headers, tools=tools, tool_choice=tool_choice
            )
            rate_limiter.record_call(endpoint_id)
            rate_limiter.record_success(endpoint_id)
            return message

        except ProviderError as pe:
            last_error = pe
            if pe.kind == "rate_limit":
                rate_limiter.record_429(endpoint_id)
            else:
                rate_limiter.record_connect_failure(endpoint_id)

        except (httpx.HTTPError, Exception) as e:
            last_error = e
            rate_limiter.record_connect_failure(endpoint_id)

    raise _ModelExhausted(last_error or NoEndpointError(f"No available endpoint for model '{model_id}'"))


async def chat_complete(
    model_id: str,
    messages: list,
    resolver: Resolver,
    rate_limiter: EndpointRateLimiter,
    user_id: str | None = None,
    tools: list | None = None,
    tool_choice: str = "auto",
) -> dict:
    """Non-streaming completion for the given model_id, with the same two-level
    failover as chat_stream (endpoint-level, then cross-model). Used for
    agent-internal calls (plan, tool decisions) — never for the final streamed
    user-facing answer, which stays on chat_stream.

    Returns the completion message dict ({"role", "content", "tool_calls", "usage"}).
    """
    models = resolver.fallback_models(model_id, user_id=user_id)

    last_error: Exception | None = None
    for candidate_model in models:
        try:
            return await _complete_one_model(
                candidate_model, messages, resolver, rate_limiter, user_id, tools, tool_choice
            )
        except _ModelExhausted as me:
            last_error = me.error
            continue
        except NoEndpointError as ne:
            last_error = ne
            continue

    if last_error:
        if isinstance(last_error, ProviderError):
            raise last_error
        if isinstance(last_error, NoEndpointError):
            raise last_error
        raise ProviderError(kind="upstream_error", message=str(last_error))
    raise NoEndpointError(f"No available endpoint for model '{model_id}'")
