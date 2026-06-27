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

Routes and agent nodes call ONLY this function.
Never import llm_core.stream_llm directly outside of this module.
"""
import httpx
import asyncio
from typing import AsyncGenerator, Callable
from app.resolver.resolver import Resolver
from app.core.rate_limiter import EndpointRateLimiter
from app.exceptions import ProviderError, NoEndpointError
from app.core.llm_core import stream_llm

async def chat_stream(
    model_id: str,
    messages: list,
    resolver: Resolver,
    rate_limiter: EndpointRateLimiter,
    on_provider_switch: Callable[[str, str], None] | None = None,
    user_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """Stream tokens from the optimal provider for the given model_id, with failover.

    Args:
        model_id:           Canonical model ID (e.g. "llama-3.3-70b").
        messages:           OAI-format message list [{"role": ..., "content": ...}, ...].
        resolver:           The Resolver instance.
        rate_limiter:       The EndpointRateLimiter instance.
        on_provider_switch: Callback invoked when a rate limit forces provider switch.
        user_id:            If given, the user's BYOK keys are preferred over shared secrets.

    Yields:
        str — individual token strings.

    Raises:
        ProviderError — on any upstream failure (rate limit, auth, network).
        NoEndpointError — if no endpoints are available.
    """
    candidates = resolver.pick(model_id, user_id=user_id)
    
    last_error = None
    for i, (url, provider_model_id, headers, endpoint_id, provider) in enumerate(candidates):
        if i > 0 and on_provider_switch:
            prev_provider = candidates[i - 1][4]
            if asyncio.iscoroutinefunction(on_provider_switch):
                await on_provider_switch(prev_provider, provider)
            else:
                on_provider_switch(prev_provider, provider)
            
        try:
            tokens_yielded = 0
            async for token in stream_llm(url, provider_model_id, messages, headers):
                if tokens_yielded == 0:
                    rate_limiter.record_call(endpoint_id)
                    rate_limiter.record_success(endpoint_id)
                tokens_yielded += 1
                yield token
            
            if tokens_yielded > 0:
                return
            else:
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
            
    if last_error:
        if isinstance(last_error, ProviderError):
            raise last_error
        raise ProviderError(kind="upstream_error", message=str(last_error))
    raise NoEndpointError(f"No available endpoint for model '{model_id}'")
