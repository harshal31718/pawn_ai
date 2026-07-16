"""Tests for app.core.title.derive_fallback_title (the instant, no-LLM default
chat title) and routes/chat.py's generate_title falling back to it correctly."""

from unittest.mock import MagicMock, patch

import pytest

from app.core.title import derive_fallback_title


def test_derive_fallback_title_short_prompt_used_verbatim():
    assert derive_fallback_title("Plan a trip to Iceland") == "Plan a trip to Iceland"


def test_derive_fallback_title_collapses_whitespace():
    assert derive_fallback_title("  hello\n\n  world  ") == "hello world"


def test_derive_fallback_title_empty_or_whitespace_only_is_new_chat():
    assert derive_fallback_title("") == "New Chat"
    assert derive_fallback_title("   \n\t  ") == "New Chat"


def test_derive_fallback_title_truncates_at_word_boundary_with_ellipsis():
    long_prompt = "Write a detailed comparison of monetary policy transmission mechanisms across regimes"
    title = derive_fallback_title(long_prompt)
    assert title.endswith("…")
    assert len(title) <= 41  # TITLE_MAX_CHARS (40) + ellipsis
    assert not title[:-1].endswith(" ")  # no trailing space before the ellipsis
    # Never cuts mid-word: every word in the truncated title is a whole
    # word from the original prompt.
    words = title.rstrip("…").split(" ")
    for w in words:
        assert w in long_prompt.split(" ")


def test_derive_fallback_title_no_space_to_break_on_still_bounded():
    """A single very long word with no spaces at all must still truncate
    (hard cut) rather than return the whole thing unbounded."""
    title = derive_fallback_title("a" * 100)
    assert title.endswith("…")
    assert len(title) <= 41


# ── routes/chat.py's generate_title fallback ─────────────────────────────────

@pytest.mark.asyncio
async def test_generate_title_falls_back_to_derived_title_on_llm_failure():
    """Regression test for the real bug found 2026-07-16: generate_title used
    to call pick_model_by_capability("fast") WITHOUT user_id, so it could pick
    a model the user holds no BYOK key for; chat_stream (called with the real
    user_id) would then fail, the exception was swallowed, and the hardcoded
    "New Chat" was returned forever -- never anything prompt-derived. Now it
    must fall back to derive_fallback_title instead."""
    from app.routes.chat import generate_title

    resolver = MagicMock()
    resolver.pick_model_by_capability.side_effect = Exception("no usable model for this user")

    title = await generate_title(
        "Plan a trip to Iceland", resolver, rate_limiter=None, user_id="u1"
    )
    assert title == "Plan a trip to Iceland"


@pytest.mark.asyncio
async def test_generate_title_passes_user_id_to_pick_model_by_capability():
    """The actual bug: user_id must reach pick_model_by_capability, not just
    the later chat_stream call, or the picked model may not be one the user
    actually holds a key for."""
    from app.routes.chat import generate_title

    resolver = MagicMock()
    resolver.pick_model_by_capability.return_value = "gemini-2.5-flash-lite"

    async def fake_chat_stream(*args, **kwargs):
        yield "Iceland Trip"

    with patch("app.routes.chat.chat_stream", side_effect=fake_chat_stream):
        await generate_title("Plan a trip to Iceland", resolver, rate_limiter=None, user_id="u1")

    resolver.pick_model_by_capability.assert_called_once_with("fast", user_id="u1")


@pytest.mark.asyncio
async def test_generate_title_uses_llm_result_when_it_succeeds():
    from app.routes.chat import generate_title

    resolver = MagicMock()
    resolver.pick_model_by_capability.return_value = "gemini-2.5-flash-lite"

    async def fake_chat_stream(*args, **kwargs):
        yield "Iceland "
        yield "Trip Planning"

    with patch("app.routes.chat.chat_stream", side_effect=fake_chat_stream):
        title = await generate_title("Plan a trip to Iceland", resolver, rate_limiter=None, user_id="u1")

    assert title == "Iceland Trip Planning"
