"""
normalize.py — Single entry point for all LLM calls.

Public API:
    async def chat_stream(provider: str, messages: list, model: str | None = None)

Routes and agent nodes call ONLY this function.
Never import llm_core.stream_llm directly outside of this module.

Provider priority (fastest → most reliable → fallbacks):
    groq > cerebras > gemini > huggingface > github > openrouter
"""
from app.core.llm_core import stream_llm, _detect_provider, _provider_headers
from app.config import (
    GEMINI_API_KEY,
    CEREBRAS_API_KEY,
    GROQ_API_KEY,
    HUGGINGFACE_API_KEY,
    GITHUB_API_KEY,
    OPENROUTER_API_KEY,
)
from app.exceptions import ProviderError

# Provider catalogue — data, not code.
# Add a new provider: add one entry here, one secret, done.
PROVIDERS: dict[str, dict] = {
    "groq": {
        "url":   "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "key":   lambda: GROQ_API_KEY,
    },
    "cerebras": {
        "url":   "https://api.cerebras.ai/v1",
        "model": "llama-3.3-70b",
        "key":   lambda: CEREBRAS_API_KEY,
    },
    "gemini": {
        "url":   "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.5-flash",
        "key":   lambda: GEMINI_API_KEY,
    },
    "huggingface": {
        "url":   "https://api-inference.huggingface.co/v1",
        "model": "meta-llama/Llama-3.3-70B-Instruct",
        "key":   lambda: HUGGINGFACE_API_KEY,
    },
    "github": {
        "url":   "https://models.inference.ai.azure.com",
        "model": "meta-llama-3.3-70b-instruct",
        "key":   lambda: GITHUB_API_KEY,
    },
    "openrouter": {
        "url":   "https://openrouter.ai/api/v1",
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        "key":   lambda: OPENROUTER_API_KEY,
    },
}


async def chat_stream(provider: str, messages: list, model: str | None = None):
    """Stream tokens from the given provider.

    Args:
        provider: Key from PROVIDERS (e.g. "groq", "gemini", "cerebras").
        messages: OAI-format message list [{"role": ..., "content": ...}, ...].
        model:    Override the provider's default model (optional).

    Yields:
        str — individual token strings.

    Raises:
        ProviderError — on any upstream failure (rate limit, auth, network).
    """
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise ProviderError(
            kind="unknown_provider",
            message=f"Unknown provider: '{provider}'. Valid: {list(PROVIDERS)}",
        )

    url      = cfg["url"]
    mdl      = model or cfg["model"]
    api_key  = cfg["key"]()
    provider_type = _detect_provider(url)
    headers  = _provider_headers(provider_type, api_key, url)

    async for token in stream_llm(url, mdl, messages, headers):
        yield token
