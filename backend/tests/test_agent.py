"""Tests for the graph v2 orchestrator (Phase A / A.6): classify -> direct_answer
| plan -> execute -> final. The old ReAct protocol (parser.py, routing.py,
build_agent_prompt, route_action) is deleted, not tested here."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.graph import (
    _memory_hit_lines,
    classify_node,
    direct_answer_node,
    execute_node,
    final_node,
    plan_node,
    route_after_classify,
)
from app.constants import AGENT_MAX_ITERATIONS, AGENT_MAX_TOKENS


def _state(**overrides):
    base = {
        "messages": [{"role": "user", "content": "hi"}],
        "user_id": "u1",
        "conversation_id": "c1",
        "user_model_id": "gemini-2.5-flash",
        "has_doc": False,
        "scope_type": None,
        "scope_id": None,
        "difficulty": "light",
        "needs_agent": False,
        "plan": [],
        "tool_log": [],
        "tokens_used": 0,
        "citations": [],
        "final_answer": None,
    }
    base.update(overrides)
    return base


# ── classify_node / routing ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_classify_node_light_message():
    with patch("app.agent.graph.router_classify", new=AsyncMock(return_value={"difficulty": "light", "needs_agent": False})):
        res = await classify_node(_state())
    assert res == {"difficulty": "light", "needs_agent": False}


@pytest.mark.asyncio
async def test_classify_node_heavy_message():
    state = _state(messages=[{"role": "user", "content": "please analyze this deeply"}])
    with patch("app.agent.graph.router_classify", new=AsyncMock(return_value={"difficulty": "heavy", "needs_agent": True})):
        res = await classify_node(state)
    assert res == {"difficulty": "heavy", "needs_agent": True}


def test_route_after_classify_light_goes_direct():
    assert route_after_classify({"needs_agent": False}) == "direct_answer"


def test_route_after_classify_heavy_goes_to_plan():
    assert route_after_classify({"needs_agent": True}) == "plan"


# ── direct_answer_node: THE fast path, zero agent overhead ─────────────────

@pytest.mark.asyncio
async def test_direct_answer_streams_with_no_step_events():
    """'hello' must incur zero agent overhead -- no step/plan events, just
    tokens and the provider marker."""
    dispatched = []

    async def fake_dispatch(name, data):
        dispatched.append(name)

    async def mock_stream(*args, **kwargs):
        yield "Hello"
        yield " there"

    with patch("app.agent.graph.adispatch_custom_event", side_effect=fake_dispatch):
        with patch("app.core.normalize.chat_stream", side_effect=mock_stream):
            res = await direct_answer_node(_state())

    assert res["final_answer"] == "Hello there"
    assert "step" not in dispatched  # zero agent overhead
    assert "token" in dispatched
    assert "final_provider" in dispatched


# ── plan_node ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_plan_node_skipped_for_light_difficulty():
    """Light-but-needs-agent (e.g. a bare URL) skips planning entirely."""
    state = _state(difficulty="light", needs_agent=True)
    with patch("app.core.normalize.chat_complete", new=AsyncMock()) as mock_complete:
        res = await plan_node(state)
    assert res == {"plan": []}
    mock_complete.assert_not_called()


@pytest.mark.asyncio
async def test_plan_node_produces_short_plan_with_tool_choice_none():
    state = _state(difficulty="heavy", needs_agent=True, messages=[{"role": "user", "content": "research X vs Y"}])

    async def fake_complete(model_id, messages, resolver, rate_limiter, user_id=None, tools=None, tool_choice="auto"):
        assert tool_choice == "none"
        return {"role": "assistant", "content": "1. Search for X\n2. Search for Y\n3. Compare", "usage": {"total_tokens": 50}}

    dispatched = []

    async def fake_dispatch(name, data):
        dispatched.append((name, data))

    with patch("app.agent.graph.adispatch_custom_event", side_effect=fake_dispatch):
        with patch("app.core.normalize.chat_complete", side_effect=fake_complete):
            res = await plan_node(state)

    assert res["plan"] == ["1. Search for X", "2. Search for Y", "3. Compare"]
    assert res["tokens_used"] == 50
    assert any(name == "step" and data.get("label") == "Plan" for name, data in dispatched)


@pytest.mark.asyncio
async def test_plan_node_caps_at_five_lines():
    state = _state(difficulty="heavy", needs_agent=True)

    async def fake_complete(*args, **kwargs):
        lines = "\n".join(f"{i}. step" for i in range(1, 9))
        return {"role": "assistant", "content": lines, "usage": {}}

    with patch("app.core.normalize.chat_complete", side_effect=fake_complete):
        with patch("app.agent.graph.adispatch_custom_event", new=AsyncMock()):
            res = await plan_node(state)
    assert len(res["plan"]) == 5


@pytest.mark.asyncio
async def test_plan_node_failure_falls_back_to_empty_plan():
    state = _state(difficulty="heavy", needs_agent=True)

    async def failing_complete(*args, **kwargs):
        raise RuntimeError("no endpoint")

    with patch("app.core.normalize.chat_complete", side_effect=failing_complete):
        res = await plan_node(state)
    assert res["plan"] == []


# ── execute_node: the tool loop ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_node_no_tool_calls_stops_immediately():
    state = _state(difficulty="heavy", needs_agent=True)

    async def fake_complete(*args, **kwargs):
        return {"role": "assistant", "content": "no tools needed", "tool_calls": None, "usage": {"total_tokens": 10}}

    with patch("app.core.normalize.chat_complete", side_effect=fake_complete):
        res = await execute_node(state)

    assert res["tool_log"] == []
    assert res["tokens_used"] == 10


@pytest.mark.asyncio
async def test_execute_node_runs_a_tool_call_and_logs_it():
    state = _state(difficulty="heavy", needs_agent=True)
    call_count = {"n": 0}

    async def fake_complete(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {
                "role": "assistant", "content": "", "usage": {"total_tokens": 5},
                "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "calculator", "arguments": '{"expression": "2+2"}'}}],
            }
        return {"role": "assistant", "content": "the answer is 4", "tool_calls": None, "usage": {"total_tokens": 5}}

    with patch("app.core.normalize.chat_complete", side_effect=fake_complete):
        with patch("app.agent.graph.adispatch_custom_event", new=AsyncMock()):
            res = await execute_node(state)

    assert len(res["tool_log"]) == 1
    assert res["tool_log"][0]["name"] == "calculator"
    assert res["tool_log"][0]["observation"] == "4"
    assert res["tool_log"][0]["agent"] == "main"
    assert res["tokens_used"] == 10


@pytest.mark.asyncio
async def test_execute_node_unknown_tool_returns_tool_error_not_raise():
    state = _state(difficulty="heavy", needs_agent=True)
    call_count = {"n": 0}

    async def fake_complete(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {
                "role": "assistant", "content": "", "usage": {},
                "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "nonexistent_tool", "arguments": "{}"}}],
            }
        return {"role": "assistant", "content": "done", "tool_calls": None, "usage": {}}

    with patch("app.core.normalize.chat_complete", side_effect=fake_complete):
        with patch("app.agent.graph.adispatch_custom_event", new=AsyncMock()):
            res = await execute_node(state)  # must not raise

    assert "TOOL_ERROR" in res["tool_log"][0]["observation"]


@pytest.mark.asyncio
async def test_execute_node_stops_at_max_iterations():
    """A model that always calls a tool must be stopped by AGENT_MAX_ITERATIONS,
    not loop forever."""
    state = _state(difficulty="heavy", needs_agent=True)

    async def always_calls_tool(*args, **kwargs):
        return {
            "role": "assistant", "content": "", "usage": {},
            "tool_calls": [{"id": "call_x", "type": "function", "function": {"name": "get_datetime", "arguments": "{}"}}],
        }

    with patch("app.core.normalize.chat_complete", side_effect=always_calls_tool):
        with patch("app.agent.graph.adispatch_custom_event", new=AsyncMock()):
            res = await execute_node(state)

    assert len(res["tool_log"]) == AGENT_MAX_ITERATIONS
    assert res["messages"][-1] == {"role": "system", "content": "budget exhausted — answer with what you have"}


@pytest.mark.asyncio
async def test_execute_node_stops_when_token_budget_exceeded():
    state = _state(difficulty="heavy", needs_agent=True, tokens_used=AGENT_MAX_TOKENS)

    with patch("app.core.normalize.chat_complete", new=AsyncMock()) as mock_complete:
        with patch("app.agent.graph.adispatch_custom_event", new=AsyncMock()):
            res = await execute_node(state)

    mock_complete.assert_not_called()  # budget already exhausted before the first call
    assert res["messages"][-1] == {"role": "system", "content": "budget exhausted — answer with what you have"}


@pytest.mark.asyncio
async def test_execute_node_tool_exception_becomes_tool_error_observation():
    """Even if a tool handler raises, run_tool's wrapper converts it to a
    TOOL_ERROR observation -- the graph must never crash on a bad tool call."""
    state = _state(difficulty="heavy", needs_agent=True)
    call_count = {"n": 0}

    async def fake_complete(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {
                "role": "assistant", "content": "", "usage": {},
                "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "calculator", "arguments": "not json"}}],
            }
        return {"role": "assistant", "content": "done", "tool_calls": None, "usage": {}}

    with patch("app.core.normalize.chat_complete", side_effect=fake_complete):
        with patch("app.agent.graph.adispatch_custom_event", new=AsyncMock()):
            res = await execute_node(state)  # must not raise

    # Malformed arguments JSON -> args={} -> calculator gets no "expression" -> TOOL_ERROR, not a crash.
    assert res["tool_log"][0]["observation"].startswith("TOOL_ERROR")


@pytest.mark.asyncio
async def test_execute_node_emits_citation_for_fetch_url():
    state = _state(difficulty="heavy", needs_agent=True)
    call_count = {"n": 0}

    async def fake_complete(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {
                "role": "assistant", "content": "", "usage": {},
                "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "fetch_url", "arguments": '{"url": "https://example.com/page"}'}}],
            }
        return {"role": "assistant", "content": "done", "tool_calls": None, "usage": {}}

    dispatched = []

    async def fake_dispatch(name, data):
        dispatched.append((name, data))

    async def fake_run_tool(spec, args, ctx):
        return "some page text"

    with patch("app.core.normalize.chat_complete", side_effect=fake_complete):
        with patch("app.agent.graph.adispatch_custom_event", side_effect=fake_dispatch):
            with patch("app.agent.graph.run_tool", side_effect=fake_run_tool):
                res = await execute_node(state)

    assert res["citations"] == [{"url": "https://example.com/page", "title": "https://example.com/page"}]
    assert any(name == "citation" for name, _ in dispatched)


# ── _memory_hit_lines ────────────────────────────────────────────────────────

def test_memory_hit_lines_preserves_embedded_newlines_in_a_single_hit():
    """A retrieved chunk's text can itself span multiple physical lines --
    the hit boundary is the next `- [conv:...]` marker, not end-of-line."""
    observation = "- [conv:abc] first sentence.\nsecond sentence still part of the same hit."
    hits = _memory_hit_lines(observation)
    assert hits == [{
        "text": "first sentence.\nsecond sentence still part of the same hit.",
        "source_conv_id": "abc",
    }]


def test_memory_hit_lines_splits_multiple_hits_with_multiline_text():
    observation = (
        "- [conv:abc] first hit line one.\nfirst hit line two.\n"
        "- [conv:def] second hit, single line."
    )
    hits = _memory_hit_lines(observation)
    assert hits == [
        {"text": "first hit line one.\nfirst hit line two.", "source_conv_id": "abc"},
        {"text": "second hit, single line.", "source_conv_id": "def"},
    ]


def test_memory_hit_lines_no_marker_returns_whole_observation():
    hits = _memory_hit_lines("[some_doc.txt] plain doc_search text")
    assert hits == [{"text": "[some_doc.txt] plain doc_search text", "source_conv_id": ""}]


# ── final_node ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_final_node_streams_answer():
    state = _state(messages=[{"role": "user", "content": "hi"}])

    async def mock_stream(*args, **kwargs):
        yield "final"
        yield " answer"

    with patch("app.core.normalize.chat_stream", side_effect=mock_stream):
        with patch("app.agent.graph.adispatch_custom_event", new=AsyncMock()):
            res = await final_node(state)

    assert res["final_answer"] == "final answer"


@pytest.mark.asyncio
async def test_final_node_digests_tool_log_not_raw_observations():
    state = _state(
        messages=[{"role": "user", "content": "hi"}],
        tool_log=[{"name": "web_search", "args": {}, "observation": "some long result " * 50, "elapsed_ms": 1, "agent": "main"}],
    )
    captured = {}

    async def capturing_stream(model_id, messages, resolver, rate_limiter, **kwargs):
        captured["messages"] = messages
        yield "ok"

    with patch("app.core.normalize.chat_stream", side_effect=capturing_stream):
        with patch("app.agent.graph.adispatch_custom_event", new=AsyncMock()):
            await final_node(state)

    digest_msg = next(m for m in captured["messages"] if "Findings from tool use" in m.get("content", ""))
    assert "web_search" in digest_msg["content"]


@pytest.mark.asyncio
async def test_final_node_respects_user_model_override():
    state = _state(user_model_id="user-picked-model", difficulty="heavy")
    captured = {}

    async def capturing_stream(model_id, messages, resolver, rate_limiter, **kwargs):
        captured["model_id"] = model_id
        yield "ok"

    with patch("app.core.normalize.chat_stream", side_effect=capturing_stream):
        with patch("app.agent.graph.adispatch_custom_event", new=AsyncMock()):
            await final_node(state)

    assert captured["model_id"] == "user-picked-model"
