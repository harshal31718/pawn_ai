"""Tests for key-aware model selection and cross-model fallback ordering.

Registry shape (user-facing models → providers):
  fast      gemini-2.5-flash-lite  [google]
  fast      glm-4.7                [cerebras]
  balanced  gemini-2.5-flash       [google]
  balanced  llama-3.3-70b          [cerebras, github, groq, huggingface, openrouter]
  balanced  gpt-oss-120b           [cerebras]
  balanced  qwen-3-32b             [cerebras]
  research  deepseek-r1            [github, huggingface, openrouter]
"""

import pytest
from unittest.mock import patch

from app.resolver.resolver import Resolver
from app.registry.loader import load_registry
from app.core.rate_limiter import EndpointRateLimiter
from app.exceptions import NoEndpointError


def _resolver():
    registry = load_registry()
    return Resolver(registry, EndpointRateLimiter())


def _keys(*allowed):
    """Patch key_store.get_key so the user only holds keys for `allowed` providers."""
    allowed_set = set(allowed)

    def fake_get_key(user_id, provider):
        return "KEY" if provider in allowed_set else None

    return patch("app.core.key_store.get_key", side_effect=fake_get_key)


# ── pick_model_by_capability is key-aware ────────────────────────────────────

def test_fast_pick_skips_unkeyed_provider():
    """With only a Google key, the fast pick must return the Google fast model,
    never the Cerebras-only glm-4.7 (the original 'cerebras' bug)."""
    r = _resolver()
    with _keys("google"):
        assert r.pick_model_by_capability("fast", user_id="u") == "gemini-2.5-flash-lite"


def test_fast_pick_returns_cerebras_when_only_cerebras_key():
    r = _resolver()
    with _keys("cerebras"):
        assert r.pick_model_by_capability("fast", user_id="u") == "glm-4.7"


def test_fast_pick_raises_when_no_keyed_model_at_level():
    """Groq serves no fast model, so a Groq-only user has no fast model."""
    r = _resolver()
    with _keys("groq"):
        with pytest.raises(NoEndpointError):
            r.pick_model_by_capability("fast", user_id="u")


def test_pick_without_user_id_keeps_legacy_behavior():
    """user_id=None skips the key check (used by tests/no-BYOK paths)."""
    r = _resolver()
    assert r.pick_model_by_capability("fast", user_id=None) == "gemini-2.5-flash-lite"


# ── F-6: Groq-priority ordering ──────────────────────────────────────────────

def test_balanced_pick_prioritizes_groq_when_user_holds_a_groq_key():
    """With both a Google and a Groq key, the default file order would return
    gemini-2.5-flash (Google, first in file order) -- but F-6 reprioritizes
    Groq-endpoint-having models first when the user holds a Groq key, so
    llama-3.3-70b (which has a Groq endpoint) must win instead."""
    r = _resolver()
    with _keys("google", "groq"):
        assert r.pick_model_by_capability("balanced", user_id="u") == "llama-3.3-70b"


def test_balanced_pick_without_groq_key_keeps_default_order():
    """No Groq key -> unaffected, still the plain file-order pick."""
    r = _resolver()
    with _keys("google"):
        assert r.pick_model_by_capability("balanced", user_id="u") == "gemini-2.5-flash"


# ── usable_user_models ───────────────────────────────────────────────────────

def test_usable_user_models_filters_by_key():
    r = _resolver()
    with _keys("google", "groq"):
        ids = {m.id for m in r.usable_user_models("u")}
    # google → both gemini models; groq → llama-3.3-70b. Cerebras-only models excluded.
    assert ids == {"gemini-2.5-flash", "gemini-2.5-flash-lite", "llama-3.3-70b"}
    assert "glm-4.7" not in ids
    assert "gpt-oss-120b" not in ids


# ── fallback_models ──────────────────────────────────────────────────────────

def test_fallback_models_primary_first_and_all_usable():
    r = _resolver()
    with _keys("google", "groq"):
        fb = r.fallback_models("gemini-2.5-flash-lite", user_id="u")
    assert fb[0] == "gemini-2.5-flash-lite"          # requested model always first
    assert "llama-3.3-70b" in fb                      # other usable model present
    assert "glm-4.7" not in fb and "qwen-3-32b" not in fb  # unkeyed models excluded
    assert len(fb) == len(set(fb))                    # de-duplicated


def test_fallback_models_orders_same_level_first():
    """Other models sharing the requested model's capability level come first."""
    r = _resolver()
    with _keys("google", "groq"):
        fb = r.fallback_models("gemini-2.5-flash", user_id="u")  # balanced
    assert fb[0] == "gemini-2.5-flash"
    # llama-3.3-70b (balanced) should precede gemini-2.5-flash-lite (fast)
    assert fb.index("llama-3.3-70b") < fb.index("gemini-2.5-flash-lite")
