"""Tests for the graph v2 orchestrator (Phase A / A.6; execute/final merged
in Phase N): classify -> direct_answer | plan -> execute -> END. The old
ReAct protocol (parser.py, routing.py, build_agent_prompt, route_action) is
deleted, not tested here. final_node no longer exists (Phase N merged it
into execute_node's own streaming tool loop) -- there is no separate
final_node test section."""

from unittest.mock import AsyncMock, patch

import pytest

from app.agent.graph import (
    DummyResolver,
    _estimate_tokens,
    _memory_hit_lines,
    classify_node,
    direct_answer_node,
    execute_node,
    plan_node,
    route_after_classify,
)
from app.constants import AGENT_MAX_ITERATIONS, AGENT_MAX_TOKENS
from app.exceptions import ProviderError


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


def _fake_stream_with_tools(turns):
    """Builds a chat_stream_with_tools-shaped fake: `turns` is a list of
    (content, tool_calls) tuples, one per expected call -- each call yields a
    "content" event (only if content is truthy) then a final "done" event.
    Raises AssertionError if called more times than turns provided (catches
    an unbounded loop in the node under test instead of hanging/IndexError)."""
    calls = {"n": 0}

    async def fake(*args, **kwargs):
        i = calls["n"]
        assert i < len(turns), "chat_stream_with_tools called more times than the test expected"
        calls["n"] += 1
        content, tool_calls = turns[i]
        if content:
            yield {"type": "content", "delta": content}
        yield {
            "type": "done",
            "tool_calls": tool_calls,
            "finish_reason": "tool_calls" if tool_calls else "stop",
            "usage": None,
        }

    fake.call_count = lambda: calls["n"]
    return fake


def _tool_call(call_id: str, name: str, arguments: str) -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


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

    async def fake_complete(model_id, messages, resolver, rate_limiter, user_id=None, tools=None, tool_choice="auto", **kwargs):
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


# ── _estimate_tokens ─────────────────────────────────────────────────────────

def test_estimate_tokens_empty_is_zero():
    assert _estimate_tokens("", None) == 0


def test_estimate_tokens_nonempty_is_at_least_one():
    assert _estimate_tokens("hi", None) >= 1


def test_estimate_tokens_scales_with_content_and_tool_calls():
    short = _estimate_tokens("hi", None)
    long_with_calls = _estimate_tokens("a long piece of reasoning text " * 10, [{"function": {"arguments": "{}"}}])
    assert long_with_calls > short


# ── execute_node: the merged streaming tool loop (Phase N) ─────────────────

@pytest.mark.asyncio
async def test_execute_node_light_agentic_pure_text_stream_no_closing_call():
    """difficulty='light' (but needs_agent=True, e.g. a URL in the message):
    O.1's mandatory closing-synthesis pass is heavy-only, so a response with
    no tool_calls still streams straight through as the final answer here --
    one call, no closing call, no tool_log. This preserves Phase N's original
    "no wasted extra call" behavior for the light+agentic path."""
    state = _state(difficulty="light", needs_agent=True)
    dispatched = []

    async def fake_dispatch(name, data):
        dispatched.append((name, data))

    fake = _fake_stream_with_tools([("no tools needed", None)])

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", side_effect=fake_dispatch):
            res = await execute_node(state)

    assert res["tool_log"] == []
    assert res["final_answer"] == "no tools needed"
    assert fake.call_count() == 1  # no closing call needed -- the loop already answered
    token_deltas = [data["delta"] for name, data in dispatched if name == "token"]
    assert "".join(token_deltas) == "no tools needed"
    assert not any(name == "step" and data.get("label") == "Composing final answer" for name, data in dispatched)


@pytest.mark.asyncio
async def test_execute_node_heavy_pure_text_stream_still_gets_closing_synthesis():
    """difficulty='heavy': O.1 fix (RC-1) -- even a clean stop with no
    tool_calls at all does NOT let the cheap orchestrator model's own text
    serve as the final answer directly; a dedicated closing-synthesis call
    always follows."""
    state = _state(difficulty="heavy", needs_agent=True)
    dispatched = []

    async def fake_dispatch(name, data):
        dispatched.append((name, data))

    fake = _fake_stream_with_tools([("no tools needed", None), ("Polished final answer.", None)])

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", side_effect=fake_dispatch):
            res = await execute_node(state)

    assert res["tool_log"] == []
    assert res["final_answer"] == "no tools neededPolished final answer."
    assert fake.call_count() == 2  # orchestrator's own text, then the O.1 closing call
    assert any(name == "step" and data.get("label") == "Composing final answer" for name, data in dispatched)


@pytest.mark.asyncio
async def test_execute_node_streams_text_before_and_after_a_tool_call():
    """The core Phase N guarantee: text the model produces before a tool call
    streams live (as `token` events), interleaved around the tool's `step`
    event -- not withheld until every tool call has finished."""
    state = _state(difficulty="heavy", needs_agent=True)
    dispatched = []

    async def fake_dispatch(name, data):
        dispatched.append((name, data))

    fake = _fake_stream_with_tools([
        ("Let me check that. ", [_tool_call("call_1", "calculator", '{"expression": "2+2"}')]),
        ("The answer is 4.", None),
        (" (verified)", None),  # O.1's mandatory closing-synthesis call, heavy difficulty
    ])

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", side_effect=fake_dispatch):
            res = await execute_node(state)

    assert res["final_answer"] == "Let me check that. The answer is 4. (verified)"
    assert len(res["tool_log"]) == 1
    assert res["tool_log"][0]["name"] == "calculator"
    assert res["tool_log"][0]["args"] == {"expression": "2+2"}
    assert res["tool_log"][0]["observation"] == "4"
    assert res["tool_log"][0]["agent"] == "main"

    idx_first_token = next(i for i, (n, _) in enumerate(dispatched) if n == "token")
    idx_calling_step = next(
        i for i, (n, d) in enumerate(dispatched) if n == "step" and d.get("label") == "Calling calculator"
    )
    idx_last_token = max(i for i, (n, _) in enumerate(dispatched) if n == "token")
    assert idx_first_token < idx_calling_step < idx_last_token, (
        "text must stream both before and after the tool card, not only after every tool call resolves"
    )


@pytest.mark.asyncio
async def test_execute_node_multi_tool_call_sequence():
    """Multiple tool_calls returned in one iteration's done event all run,
    in order, before the loop continues."""
    state = _state(difficulty="heavy", needs_agent=True)

    fake = _fake_stream_with_tools([
        ("", [
            _tool_call("call_1", "calculator", '{"expression": "2+2"}'),
            _tool_call("call_2", "get_datetime", "{}"),
        ]),
        ("done", None),
        ("", None),  # O.1's mandatory closing-synthesis call, heavy difficulty
    ])

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", new=AsyncMock()):
            res = await execute_node(state)

    assert [t["name"] for t in res["tool_log"]] == ["calculator", "get_datetime"]
    assert res["final_answer"] == "done"


@pytest.mark.asyncio
async def test_execute_node_unknown_tool_returns_tool_error_not_raise():
    state = _state(difficulty="heavy", needs_agent=True)

    fake = _fake_stream_with_tools([
        ("", [_tool_call("call_1", "nonexistent_tool", "{}")]),
        ("done", None),
        ("", None),  # O.1's mandatory closing-synthesis call, heavy difficulty
    ])

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", new=AsyncMock()):
            res = await execute_node(state)  # must not raise

    assert "TOOL_ERROR" in res["tool_log"][0]["observation"]


@pytest.mark.asyncio
async def test_execute_node_stops_at_max_iterations():
    """A model that always calls a tool must be stopped by AGENT_MAX_ITERATIONS,
    not loop forever -- then makes exactly one no-tools closing call to still
    produce a real answer (mirrors the old final_node's unconditional call)."""
    state = _state(difficulty="heavy", needs_agent=True)

    async def always_calls_tool(*args, **kwargs):
        if kwargs.get("tools"):
            yield {"type": "done", "tool_calls": [_tool_call("call_x", "get_datetime", "{}")], "finish_reason": "tool_calls", "usage": None}
        else:
            yield {"type": "content", "delta": "closing answer"}
            yield {"type": "done", "tool_calls": None, "finish_reason": "stop", "usage": None}

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=always_calls_tool):
        with patch("app.agent.graph.adispatch_custom_event", new=AsyncMock()):
            res = await execute_node(state)

    assert len(res["tool_log"]) == AGENT_MAX_ITERATIONS
    nudge_idx = res["messages"].index({"role": "system", "content": "budget exhausted — answer with what you have"})
    assert res["messages"][nudge_idx + 1] == {"role": "assistant", "content": "closing answer"}
    assert res["final_answer"] == "closing answer"


@pytest.mark.asyncio
async def test_execute_node_stops_when_token_budget_exceeded():
    """Budget already exhausted before the first call: the tool loop itself
    never runs, but a single no-tools closing call still produces an answer
    (same "always answer" guarantee the old final_node provided)."""
    state = _state(difficulty="heavy", needs_agent=True, tokens_used=AGENT_MAX_TOKENS)

    fake = _fake_stream_with_tools([("here you go", None)])

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", new=AsyncMock()):
            res = await execute_node(state)

    assert fake.call_count() == 1  # only the closing call -- no tool-loop iteration happened
    assert res["tool_log"] == []
    assert res["messages"][-2] == {"role": "system", "content": "budget exhausted — answer with what you have"}
    assert res["messages"][-1] == {"role": "assistant", "content": "here you go"}
    assert res["final_answer"] == "here you go"


@pytest.mark.asyncio
async def test_execute_node_upstream_failure_falls_through_to_closing_call():
    """An upstream failure mid-loop (e.g. every fallback model exhausted)
    doesn't kill the turn -- the loop breaks without the budget nudge, and one
    closing call still attempts a real answer."""
    state = _state(difficulty="heavy", needs_agent=True)
    call_count = {"n": 0}

    async def fake(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise ProviderError(kind="upstream_error", message="all endpoints exhausted")
        yield {"type": "content", "delta": "recovered answer"}
        yield {"type": "done", "tool_calls": None, "finish_reason": "stop", "usage": None}

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", new=AsyncMock()):
            res = await execute_node(state)

    assert not any(m == {"role": "system", "content": "budget exhausted — answer with what you have"} for m in res["messages"])
    assert res["final_answer"] == "recovered answer"


@pytest.mark.asyncio
async def test_execute_node_upstream_failure_after_content_sent_propagates_not_falls_through():
    """The locked contract (mirrored from _stream_one_model): once a content
    token has reached the user for a given call, a mid-stream failure must
    surface directly -- NOT be swallowed and papered over with a fresh
    closing call, which would silently concatenate an unrelated second answer
    onto the truncated partial text the user already saw."""
    state = _state(difficulty="heavy", needs_agent=True)

    async def fake(*args, **kwargs):
        yield {"type": "content", "delta": "partial answer, then it breaks"}
        raise ProviderError(kind="upstream_error", message="mid-stream failure")

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", new=AsyncMock()):
            with pytest.raises(ProviderError):
                await execute_node(state)


@pytest.mark.asyncio
async def test_execute_node_tool_exception_becomes_tool_error_observation():
    """Even with malformed tool_call arguments JSON, run_tool's wrapper
    converts it to a TOOL_ERROR observation -- the graph must never crash."""
    state = _state(difficulty="heavy", needs_agent=True)

    fake = _fake_stream_with_tools([
        ("", [_tool_call("call_1", "calculator", "not json")]),
        ("done", None),
        ("", None),  # O.1's mandatory closing-synthesis call, heavy difficulty
    ])

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", new=AsyncMock()):
            res = await execute_node(state)  # must not raise

    # Malformed arguments JSON -> args={} -> calculator gets no "expression" -> TOOL_ERROR, not a crash.
    assert res["tool_log"][0]["observation"].startswith("TOOL_ERROR")


@pytest.mark.asyncio
async def test_execute_node_emits_citation_for_fetch_url():
    state = _state(difficulty="heavy", needs_agent=True)

    fake = _fake_stream_with_tools([
        ("", [_tool_call("call_1", "fetch_url", '{"url": "https://example.com/page"}')]),
        ("done", None),
        ("", None),  # O.1's mandatory closing-synthesis call, heavy difficulty
    ])

    dispatched = []

    async def fake_dispatch(name, data):
        dispatched.append((name, data))

    async def fake_run_tool(spec, args, ctx):
        return "some page text"

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", side_effect=fake_dispatch):
            with patch("app.agent.graph.run_tool", side_effect=fake_run_tool):
                res = await execute_node(state)

    assert res["citations"] == [{"url": "https://example.com/page", "title": "https://example.com/page"}]
    assert any(name == "citation" for name, _ in dispatched)


class _TieredResolver(DummyResolver):
    """Returns a distinct model id per capability level so a test can prove
    which tier a given call actually used, instead of every level
    coincidentally resolving to the same DummyResolver placeholder."""

    def pick_model_by_capability(self, level, visibility="internal", user_id=None, require_tools=False):
        return f"model-for-{level}"


@pytest.mark.asyncio
async def test_execute_node_heavy_closing_call_uses_research_tier_not_orchestrator_tier():
    """O.1 (RC-1 fix): with no explicit user model pick, the closing-synthesis
    call must resolve through ROLE_LEVELS['final_heavy']='research', not
    reuse the orchestrator's own (now 'balanced') model."""
    state = _state(difficulty="heavy", needs_agent=True, user_model_id=None)
    resolver = _TieredResolver()
    calls = []

    async def fake(model_id, *args, **kwargs):
        calls.append(model_id)
        if kwargs.get("tools"):
            yield {"type": "done", "tool_calls": None, "finish_reason": "stop", "usage": None}
        else:
            yield {"type": "content", "delta": "answer"}
            yield {"type": "done", "tool_calls": None, "finish_reason": "stop", "usage": None}

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", new=AsyncMock()):
            await execute_node(state, resolver=resolver)

    assert calls[0] == "model-for-balanced"  # orchestrator's tool-driving call
    assert calls[-1] == "model-for-research"  # O.1's dedicated closing-synthesis call


@pytest.mark.asyncio
async def test_execute_node_heavy_closing_call_degraded_emits_warning_step():
    """O.1: if the closing-synthesis call fails over away from the requested
    research-tier model, a visible trace warning is emitted -- a degraded
    answer must be labeled, not silently passed off as full quality."""
    state = _state(difficulty="heavy", needs_agent=True, user_model_id=None)
    resolver = _TieredResolver()
    dispatched = []

    async def fake_dispatch(name, data):
        dispatched.append((name, data))

    async def fake(model_id, *args, **kwargs):
        if kwargs.get("tools"):
            yield {"type": "done", "tool_calls": None, "finish_reason": "stop", "usage": None}
        else:
            # Simulate the closing call failing over to a weaker fallback model.
            on_switch = kwargs.get("on_model_switch")
            if on_switch:
                await on_switch(model_id, "llama-3.3-70b")
            yield {"type": "content", "delta": "degraded answer"}
            yield {"type": "done", "tool_calls": None, "finish_reason": "stop", "usage": None}

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", side_effect=fake_dispatch):
            await execute_node(state, resolver=resolver)

    assert any(
        name == "step" and data.get("label") == "Synthesis quality may be degraded" for name, data in dispatched
    )


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
