"""Tests for Q3.1's vision-grounded prompt enhancer -- the core enhancer
plumbing (pass 1). The routes/generate.py wiring (pass 2: Auto/Always/Off gate,
per-model schema selection, style/subject suffix composition order) is covered
in test_generate.py and test_image_session.py instead."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core import normalize
from app.core.image_models import IMAGE_MODELS, PromptSchema
from app.core.vision_enhance import (
    _build_messages,
    _looks_already_scaffolded,
    enhance_with_vision,
    needs_enhancement,
)
from app.exceptions import NoEndpointError, ProviderError


# ── per-model prompt schema ──────────────────────────────────────────────────

def test_sdxl_schema_is_keyword_scaffold_with_negative():
    schema = IMAGE_MODELS["sdxl"].prompt_schema
    assert schema.format == "keyword_scaffold"
    assert schema.wants_negative is True
    assert "lighting" in schema.system_prompt.lower() or "Rembrandt" in schema.system_prompt


def test_flux_schema_is_natural_language_no_negative():
    schema = IMAGE_MODELS["flux"].prompt_schema
    assert schema.format == "natural_language"
    assert schema.wants_negative is False
    assert "negative" not in schema.system_prompt.lower()


def test_schemas_are_distinct():
    assert IMAGE_MODELS["sdxl"].prompt_schema != IMAGE_MODELS["flux"].prompt_schema


# ── rule-based gate ───────────────────────────────────────────────────────────

def test_short_vague_prompt_needs_enhancement():
    assert needs_enhancement("a cat") is True


def test_long_scaffolded_prompt_skips_enhancement():
    prompt = (
        "portrait of a woman, shot on 85mm lens, golden hour lighting, "
        "shallow depth of field, bokeh background, film grain, detailed skin "
        "texture, warm color grading, centered composition"
    )
    assert needs_enhancement(prompt) is False


def test_long_but_not_scaffolded_prompt_still_needs_enhancement():
    prompt = " ".join(["word"] * 30)  # long, but no camera/lighting vocabulary
    assert needs_enhancement(prompt) is True


def test_looks_already_scaffolded_detects_camera_vocab():
    assert _looks_already_scaffolded("shot on Canon EOS 5D, 85mm lens") is True
    assert _looks_already_scaffolded("a cat sitting on a mat") is False


# ── multimodal content shape ─────────────────────────────────────────────────

def test_text_only_content_is_plain_string():
    messages = _build_messages("a cat", None, "system prompt")
    assert messages[1]["content"] == "a cat"


def test_image_attached_content_is_oai_parts_list():
    messages = _build_messages("a cat", "BASE64DATA", "system prompt")
    content = messages[1]["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "a cat"}
    assert content[1]["type"] == "image_url"
    assert "BASE64DATA" in content[1]["image_url"]["url"]


# ── enhance_with_vision chain ────────────────────────────────────────────────

def _fake_resolver(pick_side_effect):
    resolver = MagicMock()
    resolver.pick_model_by_capability.side_effect = pick_side_effect
    return resolver


@pytest.mark.asyncio
async def test_groq_fails_gemini_succeeds():
    resolver = _fake_resolver(["llama-4-scout", "gemini-2.5-flash"])
    rate_limiter = MagicMock()

    with patch(
        "app.core.vision_enhance.normalize.chat_complete_single_model",
        new=AsyncMock(side_effect=[
            ProviderError(kind="upstream_error", message="groq down"),
            {"role": "assistant", "content": "a refined prompt"},
        ]),
    ):
        result = await enhance_with_vision(
            "a cat", None, IMAGE_MODELS["sdxl"].prompt_schema, resolver, rate_limiter,
        )

    assert result["degraded"] is False
    assert result["used_model"] == "gemini-2.5-flash"
    assert result["prompt"] == "a refined prompt"
    # exclude_model_ids on the second call must contain the first failed model
    second_call_kwargs = resolver.pick_model_by_capability.call_args_list[1].kwargs
    assert "llama-4-scout" in second_call_kwargs["exclude_model_ids"]


@pytest.mark.asyncio
async def test_both_providers_fail_returns_raw_prompt_never_raises():
    resolver = _fake_resolver(["llama-4-scout", "gemini-2.5-flash"])
    rate_limiter = MagicMock()

    with patch(
        "app.core.vision_enhance.normalize.chat_complete_single_model",
        new=AsyncMock(side_effect=ProviderError(kind="upstream_error", message="down")),
    ):
        result = await enhance_with_vision(
            "a cat", None, IMAGE_MODELS["sdxl"].prompt_schema, resolver, rate_limiter,
        )

    assert result == {"prompt": "a cat", "negative": None, "used_model": None, "degraded": True}


@pytest.mark.asyncio
async def test_no_vision_model_available_returns_raw_prompt():
    resolver = _fake_resolver(NoEndpointError("no vision model"))
    rate_limiter = MagicMock()

    result = await enhance_with_vision(
        "a cat", None, IMAGE_MODELS["sdxl"].prompt_schema, resolver, rate_limiter,
    )

    assert result["degraded"] is True
    assert result["prompt"] == "a cat"


@pytest.mark.asyncio
async def test_sdxl_negative_prompt_split_out():
    resolver = _fake_resolver(["llama-4-scout"])
    rate_limiter = MagicMock()

    with patch(
        "app.core.vision_enhance.normalize.chat_complete_single_model",
        new=AsyncMock(return_value={
            "role": "assistant",
            "content": "detailed cat portrait, 85mm lens\nNegative: blurry, low quality",
        }),
    ):
        result = await enhance_with_vision(
            "a cat", None, IMAGE_MODELS["sdxl"].prompt_schema, resolver, rate_limiter,
        )

    assert result["prompt"] == "detailed cat portrait, 85mm lens"
    assert result["negative"] == "blurry, low quality"


@pytest.mark.asyncio
async def test_sdxl_negative_prompt_split_out_when_model_uses_avoid_marker():
    """Regression test (found live 2026-07-17): a real vision model used
    "Avoid:" instead of the requested "Negative:" marker -- the old exact-
    literal-only marker list left that text stuck in the positive prompt sent
    to generation instead of being split into its own negative_prompt field."""
    resolver = _fake_resolver(["llama-4-scout"])
    rate_limiter = MagicMock()

    with patch(
        "app.core.vision_enhance.normalize.chat_complete_single_model",
        new=AsyncMock(return_value={
            "role": "assistant",
            "content": "detailed cat portrait, 85mm lens\nAvoid: cartoonish, low resolution",
        }),
    ):
        result = await enhance_with_vision(
            "a cat", None, IMAGE_MODELS["sdxl"].prompt_schema, resolver, rate_limiter,
        )

    assert result["prompt"] == "detailed cat portrait, 85mm lens"
    assert result["negative"] == "cartoonish, low resolution"


@pytest.mark.asyncio
async def test_flux_never_gets_negative_prompt():
    resolver = _fake_resolver(["gemini-2.5-flash"])
    rate_limiter = MagicMock()

    with patch(
        "app.core.vision_enhance.normalize.chat_complete_single_model",
        new=AsyncMock(return_value={"role": "assistant", "content": "a photorealistic cat in a sunlit room"}),
    ):
        result = await enhance_with_vision(
            "a cat", None, IMAGE_MODELS["flux"].prompt_schema, resolver, rate_limiter,
        )

    assert result["negative"] is None
    assert result["prompt"] == "a photorealistic cat in a sunlit room"


@pytest.mark.asyncio
async def test_chat_complete_single_model_never_falls_over_to_a_different_model():
    """Regression test for the code-review finding: normalize.chat_complete's
    own cross-model fallback (resolver.fallback_models()) isn't vision-aware
    and would silently swap in a same-capability-level text-only model. This
    is exactly why enhance_with_vision must call chat_complete_single_model,
    not chat_complete -- it must raise rather than trying any model_id other
    than the one it was given, however many endpoints that one model has.

    Uses a mocked resolver (matching test_agent.py's convention for vision
    paths) rather than the real seeded test registry, since app/registry/
    seed.py predates F-11 and has no supports_vision-flagged models to
    resolve against."""
    resolver = MagicMock()
    resolver.pick.return_value = [
        ("https://api.groq.com/openai/v1", "meta-llama/llama-4-scout-17b-16e-instruct",
         {"Authorization": "Bearer KEY"}, "ep-llama-4-scout-groq", "groq"),
    ]
    rate_limiter = MagicMock()
    rate_limiter.can_use.return_value = True

    async def always_fails(url, model, messages, headers, tools=None, tool_choice="auto"):
        raise ProviderError(kind="upstream_error", message="groq down")

    with patch("app.core.normalize._chat_complete_llm", side_effect=always_fails):
        with pytest.raises(ProviderError):
            await normalize.chat_complete_single_model(
                model_id="llama-4-scout",
                messages=[{"role": "user", "content": "hi"}],
                resolver=resolver,
                rate_limiter=rate_limiter,
                user_id="u",
            )

    # the only model ever resolved is the one explicitly passed in -- no
    # resolver.fallback_models() call, no second resolver.pick() for a
    # different model_id.
    resolver.pick.assert_called_once_with("llama-4-scout", user_id="u")
    resolver.fallback_models.assert_not_called()


@pytest.mark.asyncio
async def test_image_b64_passed_through_to_messages():
    resolver = _fake_resolver(["llama-4-scout"])
    rate_limiter = MagicMock()
    captured = {}

    async def fake_chat_complete(**kwargs):
        captured["messages"] = kwargs["messages"]
        return {"role": "assistant", "content": "enhanced"}

    with patch("app.core.vision_enhance.normalize.chat_complete_single_model", new=fake_chat_complete):
        await enhance_with_vision(
            "a cat", "IMGDATA", IMAGE_MODELS["sdxl"].prompt_schema, resolver, rate_limiter,
        )

    user_content = captured["messages"][1]["content"]
    assert isinstance(user_content, list)
    assert "IMGDATA" in user_content[1]["image_url"]["url"]
