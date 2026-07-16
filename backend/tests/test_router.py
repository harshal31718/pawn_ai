"""Tests for the model router (Phase A / A.5): heuristic tier trigger cases,
LLM fallback tier (only when the heuristic tier abstains), parse-failure
defaults, and the final-model user-override rule."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core import router
from app.core.rate_limiter import EndpointRateLimiter
from app.registry.loader import load_registry
from app.resolver.resolver import Resolver


def _resolver():
    return Resolver(load_registry(), EndpointRateLimiter())


def _msgs(text: str):
    return [{"role": "user", "content": text}]


# ── heuristic tier: each heavy trigger individually ─────────────────────────

@pytest.mark.asyncio
async def test_heavy_char_threshold_trigger():
    text = "a" * (router.ROUTER_HEAVY_CHAR_THRESHOLD + 1)
    decision = await router.classify(_msgs(text), has_doc=False, has_tools_likely=False)
    assert decision["difficulty"] == "heavy"


@pytest.mark.asyncio
async def test_code_block_trigger():
    text = "short but has a code block\n```python\nprint(1)\n```"
    decision = await router.classify(_msgs(text), has_doc=False, has_tools_likely=False)
    assert decision["difficulty"] == "heavy"


@pytest.mark.parametrize(
    "keyword", ["plan", "analyze", "debug", "prove", "compare", "research", "step by step", "why"]
)
@pytest.mark.asyncio
async def test_heavy_keyword_triggers(keyword):
    decision = await router.classify(_msgs(f"please {keyword} this for me"), has_doc=False, has_tools_likely=False)
    assert decision["difficulty"] == "heavy"


@pytest.mark.asyncio
async def test_heavy_keyword_is_word_boundary_not_substring():
    """'why' must not match inside 'whys' or similar -- word boundary only."""
    decision = await router.classify(_msgs("Explaining whystuff is fine"), has_doc=False, has_tools_likely=False)
    # No other trigger fires and length < light threshold, so this must NOT be
    # forced heavy by a false substring match on "why".
    assert decision["difficulty"] == "light"


@pytest.mark.asyncio
async def test_doc_attached_trigger():
    decision = await router.classify(_msgs("summarize this"), has_doc=True, has_tools_likely=False)
    assert decision["difficulty"] == "heavy"


@pytest.mark.asyncio
async def test_prior_turn_used_tools_trigger():
    decision = await router.classify(_msgs("ok now what"), has_doc=False, has_tools_likely=True)
    assert decision["difficulty"] == "heavy"


# ── heuristic tier: light ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_short_plain_message_is_light():
    decision = await router.classify(_msgs("hi"), has_doc=False, has_tools_likely=False)
    assert decision["difficulty"] == "light"
    assert decision["needs_agent"] is False


# ── needs_agent triggers ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_needs_agent_true_when_heavy():
    decision = await router.classify(_msgs("please analyze this"), has_doc=False, has_tools_likely=False)
    assert decision["needs_agent"] is True


@pytest.mark.asyncio
async def test_needs_agent_true_for_url_even_when_light():
    decision = await router.classify(_msgs("check https://example.com"), has_doc=False, has_tools_likely=False)
    assert decision["difficulty"] == "light"
    assert decision["needs_agent"] is True


@pytest.mark.asyncio
async def test_needs_agent_true_for_time_sensitive_with_search_key():
    decision = await router.classify(
        _msgs("what's the latest price"), has_doc=False, has_tools_likely=False, has_search_key=True
    )
    assert decision["difficulty"] == "light"
    assert decision["needs_agent"] is True


@pytest.mark.asyncio
async def test_needs_agent_false_for_time_sensitive_without_search_key():
    """The time-sensitive trigger only fires when a search key is configured
    -- otherwise there's no tool that could act on it."""
    decision = await router.classify(
        _msgs("what's the latest price"), has_doc=False, has_tools_likely=False, has_search_key=False
    )
    assert decision["needs_agent"] is False


@pytest.mark.asyncio
async def test_needs_agent_true_for_image_gen_request_with_kaggle_creds():
    """F-11 regression: 'generate an image of X' is short with no URL/heavy
    keyword, so without this trigger it would route light+needs_agent=False
    -- the direct_answer fast path has no tools bound at all, so
    generate_image could never actually be invoked."""
    decision = await router.classify(
        _msgs("can you generate an image of a person eating an apple"),
        has_doc=False, has_tools_likely=False, has_kaggle_creds=True,
    )
    assert decision["needs_agent"] is True


@pytest.mark.asyncio
async def test_needs_agent_false_for_image_gen_request_without_kaggle_creds():
    """The image-gen trigger only fires when Kaggle creds are configured --
    otherwise generate_image wouldn't even be in the toolset anyway."""
    decision = await router.classify(
        _msgs("can you generate an image of a person eating an apple"),
        has_doc=False, has_tools_likely=False, has_kaggle_creds=False,
    )
    assert decision["needs_agent"] is False


# ── LLM fallback tier: only invoked when the heuristic tier abstains ────────

@pytest.mark.asyncio
async def test_fallback_not_invoked_when_heuristic_decides_heavy():
    resolver = MagicMock()
    with patch("app.core.router.chat_complete", new=AsyncMock()) as mock_complete:
        await router.classify(_msgs("please analyze this"), has_doc=False, has_tools_likely=False, resolver=resolver)
    mock_complete.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_not_invoked_when_heuristic_decides_light():
    resolver = MagicMock()
    with patch("app.core.router.chat_complete", new=AsyncMock()) as mock_complete:
        await router.classify(_msgs("hi"), has_doc=False, has_tools_likely=False, resolver=resolver)
    mock_complete.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_invoked_for_ambiguous_length_band():
    """Text length strictly between LIGHT and HEAVY thresholds, with no other
    trigger, is ambiguous -- must defer to the LLM fallback tier."""
    text = "a" * (router.ROUTER_LIGHT_CHAR_THRESHOLD + 50)
    assert len(text) < router.ROUTER_HEAVY_CHAR_THRESHOLD

    resolver = _resolver()
    rate_limiter = resolver._rate_limiter

    async def fake_complete(model_id, messages, resolver_, rate_limiter_, user_id=None, tools=None):
        return {"role": "assistant", "content": "light"}

    with patch("app.core.router.chat_complete", side_effect=fake_complete) as mock_complete:
        decision = await router.classify(
            _msgs(text), has_doc=False, has_tools_likely=False, resolver=resolver, rate_limiter=rate_limiter
        )
    mock_complete.assert_called_once()
    assert decision["difficulty"] == "light"


@pytest.mark.asyncio
async def test_fallback_no_resolver_available_defaults_heavy():
    """Ambiguous band, but no resolver/rate_limiter passed at all -- fails
    toward capability rather than guessing."""
    text = "a" * (router.ROUTER_LIGHT_CHAR_THRESHOLD + 50)
    decision = await router.classify(_msgs(text), has_doc=False, has_tools_likely=False)
    assert decision == {"difficulty": "heavy", "needs_agent": True}


@pytest.mark.asyncio
async def test_fallback_parses_heavy_response():
    text = "a" * (router.ROUTER_LIGHT_CHAR_THRESHOLD + 50)
    resolver = _resolver()

    async def fake_complete(model_id, messages, resolver_, rate_limiter_, user_id=None, tools=None):
        return {"role": "assistant", "content": " Heavy "}

    with patch("app.core.router.chat_complete", side_effect=fake_complete):
        decision = await router.classify(
            _msgs(text), has_doc=False, has_tools_likely=False, resolver=resolver, rate_limiter=resolver._rate_limiter
        )
    assert decision["difficulty"] == "heavy"
    assert decision["needs_agent"] is True


@pytest.mark.asyncio
async def test_fallback_parse_failure_defaults_heavy():
    """An unparseable model response must default to heavy/needs_agent=True."""
    text = "a" * (router.ROUTER_LIGHT_CHAR_THRESHOLD + 50)
    resolver = _resolver()

    async def fake_complete(model_id, messages, resolver_, rate_limiter_, user_id=None, tools=None):
        return {"role": "assistant", "content": "I'm not sure, maybe both?"}

    with patch("app.core.router.chat_complete", side_effect=fake_complete):
        decision = await router.classify(
            _msgs(text), has_doc=False, has_tools_likely=False, resolver=resolver, rate_limiter=resolver._rate_limiter
        )
    assert decision == {"difficulty": "heavy", "needs_agent": True}


@pytest.mark.asyncio
async def test_fallback_model_error_defaults_heavy():
    """If the fallback model call itself raises (rate limit, no endpoint,
    etc.), that must not propagate -- default to heavy/needs_agent=True."""
    text = "a" * (router.ROUTER_LIGHT_CHAR_THRESHOLD + 50)
    resolver = _resolver()

    async def failing_complete(*args, **kwargs):
        raise RuntimeError("no endpoint available")

    with patch("app.core.router.chat_complete", side_effect=failing_complete):
        decision = await router.classify(
            _msgs(text), has_doc=False, has_tools_likely=False, resolver=resolver, rate_limiter=resolver._rate_limiter
        )
    assert decision == {"difficulty": "heavy", "needs_agent": True}


# ── ROLE_LEVELS ──────────────────────────────────────────────────────────────

def test_role_levels_matches_plan_spec():
    # orchestrator = "balanced" (not "fast"): O.1 companion fix, reply-quality
    # plan Appendix A.4 -- glm-4.7 moved fast->research in the registry
    # re-tiering, so "fast" alone (gemini-2.5-flash-lite + a stale
    # llama-3.3-70b at the time) was too weak to drive tool use well.
    assert router.ROLE_LEVELS == {
        "orchestrator": "balanced",
        "final_light": "fast",
        "final_heavy": "research",
        "summarizer": "fast",
        "titler": "fast",
        "subagent_researcher": "fast",
        "subagent_coder": "research",
        "subagent_summarizer": "fast",
        # F-11: direct_answer_node's image-attached branch, require_vision=True.
        "vision_answer": "balanced",
    }


# ── resolve_final_model: user override ──────────────────────────────────────

def test_resolve_final_model_user_override_wins_regardless_of_difficulty():
    resolver = MagicMock()
    resolver.pick_model_by_capability = MagicMock(return_value="should-not-be-used")

    picked_heavy = router.resolve_final_model("heavy", "user-picked-model", resolver)
    picked_light = router.resolve_final_model("light", "user-picked-model", resolver)

    assert picked_heavy == "user-picked-model"
    assert picked_light == "user-picked-model"
    resolver.pick_model_by_capability.assert_not_called()


def test_resolve_final_model_falls_back_to_role_levels_when_no_override():
    resolver = MagicMock()
    resolver.pick_model_by_capability = MagicMock(return_value="resolved-model")

    result = router.resolve_final_model("heavy", None, resolver)

    assert result == "resolved-model"
    resolver.pick_model_by_capability.assert_called_once_with("research", user_id=None)


def test_resolve_final_model_light_uses_final_light_level():
    resolver = MagicMock()
    resolver.pick_model_by_capability = MagicMock(return_value="fast-model")

    result = router.resolve_final_model("light", None, resolver)

    assert result == "fast-model"
    resolver.pick_model_by_capability.assert_called_once_with("fast", user_id=None)
