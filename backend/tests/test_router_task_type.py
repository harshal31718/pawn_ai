"""C2: task-type inference in core/router.py.

task_type is a selection PREFERENCE (see resolver.rank_candidates), so a
misclassification costs a slightly worse model pick, never a failure. That
asymmetry is why inference is heuristic-only and gets no LLM tier.
"""
import pytest

from app.constants import TASK_TYPES
from app.core.router import _infer_task_type, classify


# ── inference ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("write a python function to reverse a list", "coding"),
    ("there's a bug in my regex", "coding"),
    ("fix this traceback please", "coding"),
    ("summarize this article for me", "summarization"),
    ("give me a tldr", "summarization"),
    ("prove that the square root of 2 is irrational", "reasoning"),
    ("compare these two approaches step by step", "reasoning"),
    ("what's the capital of France", "general"),
    ("hello there", "general"),
])
def test_infer_task_type(text, expected):
    assert _infer_task_type(text) == expected


def test_fenced_code_block_is_a_coding_signal_on_its_own():
    """More reliable than any keyword -- prose about code rarely fences it."""
    assert _infer_task_type("what does this do?\n```\nx = 1\n```") == "coding"


def test_has_image_forces_vision_over_text_signals():
    assert _infer_task_type("summarize this", has_image=True) == "vision"
    assert _infer_task_type("```\ncode\n```", has_image=True) == "vision"


def test_inference_always_returns_a_valid_task_type():
    for text in ("", "   ", "!!!", "a" * 5000):
        assert _infer_task_type(text) in TASK_TYPES


# ── classify() threads task_type through every decision path ─────────────────

@pytest.mark.asyncio
async def test_heuristic_tier_carries_task_type():
    d = await classify([{"role": "user", "content": "debug this python function"}],
                       has_doc=False, has_tools_likely=False)
    assert d["task_type"] == "coding"
    assert "difficulty" in d and "needs_agent" in d


@pytest.mark.asyncio
async def test_no_resolver_default_still_carries_task_type():
    """The ambiguous band with no resolver fails toward capability
    (heavy/needs_agent) -- but must still report a task type."""
    text = "x" * 500   # between LIGHT and HEAVY thresholds -> ambiguous band
    d = await classify([{"role": "user", "content": text + " summarize"}],
                       has_doc=False, has_tools_likely=False,
                       resolver=None, rate_limiter=None)
    assert d["difficulty"] == "heavy"
    assert d["needs_agent"] is True
    assert d["task_type"] in TASK_TYPES


@pytest.mark.asyncio
async def test_has_image_propagates_through_classify():
    d = await classify([{"role": "user", "content": "what is this"}],
                       has_doc=False, has_tools_likely=False, has_image=True)
    assert d["task_type"] == "vision"
