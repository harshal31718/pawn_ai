"""Tests for the graph v2 orchestrator (Phase A / A.6; execute/final merged
in Phase N; verify added in O.3): classify -> direct_answer | plan -> execute
-> [verify -> execute]* -> END. The old ReAct protocol (parser.py, routing.py,
build_agent_prompt, route_action) is deleted, not tested here. final_node no
longer exists (Phase N merged it into execute_node's own streaming tool loop)
-- there is no separate final_node test section."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.graph import (
    DummyResolver,
    _estimate_tokens,
    _memory_hit_lines,
    _used_image_gen_tool,
    _used_research_tools,
    classify_node,
    direct_answer_node,
    execute_node,
    plan_node,
    route_after_classify,
    route_after_execute,
    route_after_verify,
    verify_node,
)
from app.constants import AGENT_MAX_ITERATIONS, AGENT_MAX_TOKENS, VERIFY_MAX_REVISIONS
from app.exceptions import NoEndpointError, ProviderError


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
        "revision_count": 0,
        "needs_revision": False,
        "verify_draft": None,
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


@pytest.mark.asyncio
async def test_classify_node_image_attached_skips_router_entirely():
    """F-11: an image-attached turn always forces light/direct-answer without
    ever calling router_classify -- the router's text heuristics assume
    plain-string content, which a multimodal turn won't have."""
    state = _state(has_image=True, image_b64="Zm9v", image_mime="image/png")
    with patch("app.agent.graph.router_classify", new=AsyncMock()) as mock_router:
        res = await classify_node(state)
    assert res == {"difficulty": "light", "needs_agent": False}
    mock_router.assert_not_called()


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


@pytest.mark.asyncio
async def test_direct_answer_image_attached_uses_vision_capable_model_and_multimodal_content():
    """F-11: an image-attached turn overrides the user's own model pick with
    a vision-capable one (require_vision=True) and sends a multimodal
    content list (text + image_url), built fresh rather than mutating
    state["messages"] -- history stays plain-string."""
    state = _state(
        has_image=True,
        image_b64="Zm9v",
        image_mime="image/png",
        messages=[
            {"role": "user", "content": "earlier text turn"},
            {"role": "assistant", "content": "earlier reply"},
            {"role": "user", "content": "what's in this image?"},
        ],
    )
    captured = {}

    async def mock_stream(*args, **kwargs):
        captured["messages"] = kwargs.get("messages")
        captured["model_id"] = kwargs.get("model_id")
        yield "A cat."

    resolver = MagicMock()
    resolver.pick_model_by_capability.return_value = "gemini-2.5-flash"
    resolver.pick.return_value = []

    with patch("app.agent.graph.adispatch_custom_event", new=AsyncMock()):
        with patch("app.core.normalize.chat_stream", side_effect=mock_stream):
            res = await direct_answer_node(state, resolver=resolver)

    resolver.pick_model_by_capability.assert_called_once_with("balanced", user_id="u1", require_vision=True)
    assert captured["model_id"] == "gemini-2.5-flash"
    assert captured["messages"][:-1] == state["messages"][:-1]  # history untouched, plain strings
    last = captured["messages"][-1]
    assert last["role"] == "user"
    assert last["content"] == [
        {"type": "text", "text": "what's in this image?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,Zm9v"}},
    ]
    assert res["final_answer"] == "A cat."


@pytest.mark.asyncio
async def test_direct_answer_image_attached_no_vision_model_falls_back_gracefully():
    """No vision-capable model available (no matching key configured) must
    not crash the turn -- dispatches a clear explanation as the answer."""
    state = _state(has_image=True, image_b64="Zm9v", image_mime="image/png")
    resolver = MagicMock()
    resolver.pick_model_by_capability.side_effect = NoEndpointError("no vision model")

    dispatched = []

    async def fake_dispatch(name, data):
        dispatched.append((name, data))

    with patch("app.agent.graph.adispatch_custom_event", side_effect=fake_dispatch):
        res = await direct_answer_node(state, resolver=resolver)

    assert "vision-capable model" in res["final_answer"]
    assert any(name == "token" and "vision-capable model" in data["delta"] for name, data in dispatched)


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
    always follows. O.1-residual fix: the orchestrator's own clean-stop text
    must never reach the user at all (not just get followed by a second
    call) -- only the closing synthesis is dispatched, so the two can't be
    seen concatenated as two different-worded answers to the same question."""
    state = _state(difficulty="heavy", needs_agent=True)
    dispatched = []

    async def fake_dispatch(name, data):
        dispatched.append((name, data))

    fake = _fake_stream_with_tools([("no tools needed", None), ("Polished final answer.", None)])

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", side_effect=fake_dispatch):
            res = await execute_node(state)

    assert res["tool_log"] == []
    assert res["final_answer"] == "Polished final answer."  # NOT "no tools needed" + closing text
    assert fake.call_count() == 2  # orchestrator's own text, then the O.1 closing call
    token_deltas = [data["delta"] for name, data in dispatched if name == "token"]
    assert token_deltas == ["Polished final answer."]  # the orchestrator's own text was never dispatched
    assert any(name == "step" and data.get("label") == "Composing final answer" for name, data in dispatched)


@pytest.mark.asyncio
async def test_execute_node_heavy_clean_stop_does_not_pass_trailing_assistant_message():
    """F-7 fix: on a heavy turn's clean stop (no tool_calls at all), the
    orchestrator's own discarded draft must NOT be appended as a trailing
    `assistant`-role message before the mandatory closing-synthesis call --
    several providers (Gemini's OAI-compat layer) reject or empty-out a
    completions request whose final message is already assistant-authored,
    which was the root cause of the half-generation/empty-reply bug. The
    draft is still passed as context, just as a non-terminal `system` note."""
    state = _state(difficulty="heavy", needs_agent=True)
    captured_messages = []

    async def fake(*args, **kwargs):
        captured_messages.append(list(args[1]))
        if kwargs.get("tools"):
            yield {"type": "content", "delta": "no tools needed"}
            yield {"type": "done", "tool_calls": None, "finish_reason": "stop", "usage": None}
        else:
            yield {"type": "content", "delta": "Polished final answer."}
            yield {"type": "done", "tool_calls": None, "finish_reason": "stop", "usage": None}

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", new=AsyncMock()):
            res = await execute_node(state)

    assert len(captured_messages) == 2
    closing_call_messages = captured_messages[1]
    assert closing_call_messages[-1]["role"] != "assistant"
    assert "no tools needed" in closing_call_messages[-1]["content"]  # draft kept as context
    assert res["final_answer"] == "Polished final answer."


@pytest.mark.asyncio
async def test_execute_node_heavy_closing_synthesis_failure_no_content_sent_falls_back_to_loop_draft():
    """F-7 fix: if the closing-synthesis call fails outright before any
    content reached the user, the turn must not end in a silent empty reply
    -- it falls back to the tool loop's own last draft rather than raising
    (mirrors the tool loop's own upstream-failure fallback)."""
    state = _state(difficulty="heavy", needs_agent=True)

    async def fake(*args, **kwargs):
        if kwargs.get("tools"):
            yield {"type": "content", "delta": "loop's own draft answer"}
            yield {"type": "done", "tool_calls": None, "finish_reason": "stop", "usage": None}
        else:
            raise ProviderError(kind="upstream_error", message="all endpoints exhausted")

    dispatched = []

    async def fake_dispatch(name, data):
        dispatched.append((name, data))

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", side_effect=fake_dispatch):
            res = await execute_node(state)  # must NOT raise

    assert res["final_answer"] == "loop's own draft answer"
    token_deltas = [data["delta"] for name, data in dispatched if name == "token"]
    assert token_deltas == ["loop's own draft answer"]


@pytest.mark.asyncio
async def test_execute_node_heavy_double_failure_with_no_content_anywhere_falls_back_to_apology():
    """F-7 (code-reviewer WARN, closed): a heavy-but-non-research turn where
    the tool loop never runs at all (budget already exhausted on entry, so
    `content`/`last_loop_draft` stay "") AND the closing-synthesis call also
    fails outright must still get a real reply -- not a silent empty one.
    This turn never routes through verify_node (no research tools used), so
    execute_node itself must be the one to dispatch the apology fallback."""
    state = _state(difficulty="heavy", needs_agent=True, tokens_used=AGENT_MAX_TOKENS)

    async def fake(*args, **kwargs):
        raise ProviderError(kind="upstream_error", message="all endpoints exhausted")
        yield  # pragma: no cover -- unreachable; makes this an async generator like the real call site expects

    dispatched = []

    async def fake_dispatch(name, data):
        dispatched.append((name, data))

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", side_effect=fake_dispatch):
            res = await execute_node(state)  # must NOT raise, must NOT end up with an empty reply

    assert res["final_answer"]  # non-empty
    token_deltas = [data["delta"] for name, data in dispatched if name == "token"]
    assert len(token_deltas) == 1 and token_deltas[0]


@pytest.mark.asyncio
async def test_execute_node_heavy_plan_adds_delegation_nudge():
    """O.4 (reply-quality plan, RC-4 fix): a heavy turn with a plan gets an
    explicit nudge toward delegate_researcher for research sub-tasks appended
    to the injected Plan system message -- a strong default, not a hard rule."""
    state = _state(difficulty="heavy", needs_agent=True, plan=["1. Research X", "2. Research Y"])
    captured = {}

    async def fake(*args, **kwargs):
        captured["messages"] = args[1]
        yield {"type": "content", "delta": "answer"}
        yield {"type": "done", "tool_calls": None, "finish_reason": "stop", "usage": None}

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", new=AsyncMock()):
            await execute_node(state)

    plan_message = captured["messages"][0]["content"]
    assert plan_message.startswith("Plan:\n1. Research X\n2. Research Y")
    assert "delegate_researcher" in plan_message


@pytest.mark.asyncio
async def test_execute_node_light_plan_omits_delegation_nudge():
    """The nudge is gated to difficulty='heavy' (cheap where it's cheap) --
    must not fire even if a plan somehow exists on a light turn."""
    state = _state(difficulty="light", needs_agent=True, plan=["1. Research X"])
    captured = {}

    async def fake(*args, **kwargs):
        captured["messages"] = args[1]
        yield {"type": "content", "delta": "answer"}
        yield {"type": "done", "tool_calls": None, "finish_reason": "stop", "usage": None}

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", new=AsyncMock()):
            await execute_node(state)

    plan_message = captured["messages"][0]["content"]
    assert plan_message == "Plan:\n1. Research X"
    assert "delegate_researcher" not in plan_message


@pytest.mark.asyncio
async def test_execute_node_streams_text_before_a_tool_call_and_final_synthesis_after():
    """The Phase N guarantee, as refined by the O.1-residual fix: text the
    model produces BEFORE a tool call still streams live (flushed as one
    chunk right before the tool's `step` event) -- but a heavy turn's own
    clean-stop text AFTER the last tool call resolves ("The answer is 4.")
    is now intentionally never dispatched, since the mandatory closing
    synthesis ("(verified)") is the sole authoritative answer. This replaces
    the pre-fix test that asserted both the orchestrator's own post-tool text
    AND the closing synthesis were both visible -- that was the bug."""
    state = _state(difficulty="heavy", needs_agent=True)
    dispatched = []

    async def fake_dispatch(name, data):
        dispatched.append((name, data))

    fake = _fake_stream_with_tools([
        ("Let me check that. ", [_tool_call("call_1", "calculator", '{"expression": "2+2"}')]),
        ("The answer is 4.", None),  # orchestrator's own clean-stop text -- must be suppressed
        (" (verified)", None),  # O.1's mandatory closing-synthesis call, heavy difficulty
    ])

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", side_effect=fake_dispatch):
            res = await execute_node(state)

    assert res["final_answer"] == "Let me check that.  (verified)"  # NOT "...The answer is 4. (verified)"
    assert len(res["tool_log"]) == 1
    assert res["tool_log"][0]["name"] == "calculator"
    assert res["tool_log"][0]["args"] == {"expression": "2+2"}
    assert res["tool_log"][0]["observation"] == "4"
    assert res["tool_log"][0]["agent"] == "main"

    token_deltas = [data["delta"] for name, data in dispatched if name == "token"]
    assert token_deltas == ["Let me check that. ", " (verified)"]  # "The answer is 4." never dispatched

    idx_first_token = next(i for i, (n, _) in enumerate(dispatched) if n == "token")
    idx_calling_step = next(
        i for i, (n, d) in enumerate(dispatched) if n == "step" and d.get("label") == "Calling calculator"
    )
    idx_last_token = max(i for i, (n, _) in enumerate(dispatched) if n == "token")
    assert idx_first_token < idx_calling_step < idx_last_token, (
        "pre-tool-call text must still stream before the tool card; the closing synthesis after"
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
        ("done", None),  # orchestrator's own clean-stop text -- suppressed, see O.1-residual fix
        ("closing synthesis answer", None),  # O.1's mandatory closing-synthesis call, heavy difficulty
    ])

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", new=AsyncMock()):
            res = await execute_node(state)

    assert [t["name"] for t in res["tool_log"]] == ["calculator", "get_datetime"]
    assert res["final_answer"] == "closing synthesis answer"  # NOT "done" -- that text is never shown


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
async def test_execute_node_light_loop_failure_after_content_sent_propagates_not_falls_through():
    """The locked contract (mirrored from _stream_one_model): once a content
    token has reached the user for a given call, a mid-stream failure must
    surface directly -- NOT be swallowed and papered over with a fresh
    closing call, which would silently concatenate an unrelated second answer
    onto the truncated partial text the user already saw. Light (but
    agentic) turns are the only path where the tool loop's OWN content still
    streams live (heavy turns defer it -- see the O.1-residual fix and the
    heavy-closing-synthesis variant of this test below), so this is tested
    here on a light turn specifically."""
    state = _state(difficulty="light", needs_agent=True)

    async def fake(*args, **kwargs):
        yield {"type": "content", "delta": "partial answer, then it breaks"}
        raise ProviderError(kind="upstream_error", message="mid-stream failure")

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", new=AsyncMock()):
            with pytest.raises(ProviderError):
                await execute_node(state)


@pytest.mark.asyncio
async def test_execute_node_heavy_loop_failure_after_content_buffered_falls_through_to_closing_call():
    """The flip side of the O.1-residual fix: on a heavy turn, the loop's own
    content is deferred (never dispatched -- see defer_loop_content), so a
    mid-stream failure there is always safe to fall through to a fresh
    closing-synthesis attempt, even after the failing call had already
    generated (but not shown) partial text. This is new, intentionally more
    resilient behavior versus the pre-fix contract, which used to hard-fail
    the whole turn in this exact scenario."""
    state = _state(difficulty="heavy", needs_agent=True)
    call_count = {"n": 0}

    async def fake(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            yield {"type": "content", "delta": "buffered partial answer, then it breaks"}
            raise ProviderError(kind="upstream_error", message="mid-stream failure")
        yield {"type": "content", "delta": "recovered closing answer"}
        yield {"type": "done", "tool_calls": None, "finish_reason": "stop", "usage": None}

    dispatched = []

    async def fake_dispatch(name, data):
        dispatched.append((name, data))

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", side_effect=fake_dispatch):
            res = await execute_node(state)  # must NOT raise -- the buffered content was never shown

    assert res["final_answer"] == "recovered closing answer"
    token_deltas = [data["delta"] for name, data in dispatched if name == "token"]
    assert token_deltas == ["recovered closing answer"]  # the buffered, failed attempt never appears


@pytest.mark.asyncio
async def test_execute_node_heavy_closing_synthesis_failure_after_content_sent_propagates():
    """The O.1-residual fix moves the "once shown, must propagate" contract
    onto the closing-synthesis call for heavy turns, since that's now the
    only call whose content reaches the user directly (loop iterations are
    deferred). A mid-stream failure there, after real content was already
    dispatched, must still surface directly -- not be silently swallowed."""
    state = _state(difficulty="heavy", needs_agent=True)

    async def fake(*args, **kwargs):
        if kwargs.get("tools"):
            yield {"type": "done", "tool_calls": None, "finish_reason": "stop", "usage": None}
        else:
            yield {"type": "content", "delta": "closing synthesis partial, then it breaks"}
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


@pytest.mark.asyncio
async def test_execute_node_dispatches_tool_result_with_real_observation():
    """F-11 follow-up (live bug): `observation` was never sent over SSE at
    all -- only ever attached to the persisted message after the whole turn
    finished -- so anything keyed off it (ImageJobChip's job id) could never
    appear during a live stream, only after a later reload. A `tool_result`
    custom event must fire the moment the tool call itself resolves, with
    its real observation and agent tag."""
    state = _state(difficulty="light", needs_agent=True)
    dispatched = []

    async def fake_dispatch(name, data):
        dispatched.append((name, data))

    async def fake(*args, **kwargs):
        if kwargs.get("tools"):
            yield {
                "type": "done",
                "tool_calls": [_tool_call("call_1", "generate_image", '{"prompt": "a cat"}')],
                "finish_reason": "tool_calls",
                "usage": None,
            }
        else:
            yield {"type": "content", "delta": "Your image is generating."}
            yield {"type": "done", "tool_calls": None, "finish_reason": "stop", "usage": None}

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", side_effect=fake_dispatch):
            res = await execute_node(state)

    real_observation = res["tool_log"][0]["observation"]
    assert any(
        name == "tool_result"
        and data.get("name") == "generate_image"
        and data.get("observation") == real_observation
        and data.get("agent") == "main"
        for name, data in dispatched
    )


@pytest.mark.asyncio
async def test_execute_node_heavy_generate_image_call_gets_synthesis_nudge():
    """F-11 live bug: the closing-synthesis pass has no tools and no
    awareness of what generate_image actually returned -- a research-tier
    model would sometimes fabricate a fake image link (e.g. a made-up
    imgur.com URL) instead of just relaying that generation is in progress.
    A system nudge must be appended to the closing call's own messages
    whenever a generate_image call appears in this turn's tool_log."""
    state = _state(difficulty="heavy", needs_agent=True)
    captured_messages = []

    async def fake(*args, **kwargs):
        captured_messages.append(list(args[1]))
        if kwargs.get("tools"):
            yield {
                "type": "done",
                "tool_calls": [_tool_call("call_1", "generate_image", '{"prompt": "a cat"}')],
                "finish_reason": "tool_calls",
                "usage": None,
            }
        else:
            yield {"type": "content", "delta": "Your image is generating."}
            yield {"type": "done", "tool_calls": None, "finish_reason": "stop", "usage": None}

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", new=AsyncMock()):
            res = await execute_node(state)

    assert res["tool_log"][0]["name"] == "generate_image"
    closing_call_messages = captured_messages[-1]
    assert any(
        m.get("role") == "system" and "Do not invent an image URL" in m.get("content", "")
        for m in closing_call_messages
    )


def test_used_image_gen_tool_true_when_present():
    assert _used_image_gen_tool([{"name": "generate_image"}]) is True


def test_used_image_gen_tool_false_when_absent():
    assert _used_image_gen_tool([{"name": "calculator"}]) is False


# ── O.3: verify node + deep-research gating ─────────────────────────────────

def test_used_research_tools_true_for_web_search():
    assert _used_research_tools([{"name": "web_search"}]) is True


def test_used_research_tools_true_for_delegate_researcher():
    assert _used_research_tools([{"name": "delegate_researcher"}]) is True


def test_used_research_tools_false_for_non_research_tools_only():
    """A heavy-but-non-research turn (e.g. a long code task via
    delegate_coder) must not trigger the verifier."""
    assert _used_research_tools([{"name": "delegate_coder"}, {"name": "calculator"}]) is False


def test_used_research_tools_false_for_empty_log():
    assert _used_research_tools([]) is False


def test_route_after_execute_gates_on_heavy_and_research_tools():
    assert route_after_execute(_state(difficulty="heavy", tool_log=[{"name": "web_search"}])) == "verify"
    assert route_after_execute(_state(difficulty="heavy", tool_log=[{"name": "delegate_coder"}])) == "end"
    assert route_after_execute(_state(difficulty="light", tool_log=[{"name": "web_search"}])) == "end"


def test_route_after_verify_follows_needs_revision():
    assert route_after_verify(_state(needs_revision=True)) == "execute"
    assert route_after_verify(_state(needs_revision=False)) == "end"


@pytest.mark.asyncio
async def test_execute_node_buffers_closing_synthesis_when_research_tools_used():
    """O.3: a heavy turn that used web_search must NOT have its closing
    synthesis dispatched as `token` events (chat.py builds the persisted
    message purely from those) -- it's held in verify_draft for verify_node
    to check first. Combined with the O.1-residual fix, NOTHING is dispatched
    at all in this scenario: the loop's own clean-stop text is suppressed
    (see the multi-answer fix) and the closing synthesis is buffered (O.3)."""
    state = _state(
        difficulty="heavy", needs_agent=True,
        tool_log=[{"name": "web_search", "args": {}, "observation": "...", "elapsed_ms": 1, "agent": "main"}],
    )
    dispatched = []

    async def fake_dispatch(name, data):
        dispatched.append((name, data))

    # Turn 1: the loop's own iteration (clean stop, no tool_calls) -- content
    # suppressed by the O.1-residual fix. Turn 2: the mandatory O.1 closing
    # synthesis -- buffered by O.3's verify gate.
    fake = _fake_stream_with_tools([("no tools needed", None), ("Draft answer text.", None)])

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", side_effect=fake_dispatch):
            res = await execute_node(state)

    assert res["verify_draft"] == "Draft answer text."
    token_deltas = [data["delta"] for name, data in dispatched if name == "token"]
    assert token_deltas == []  # neither the suppressed loop text nor the buffered draft is dispatched
    assert res["messages"][-1] == {"role": "assistant", "content": "Draft answer text."}


@pytest.mark.asyncio
async def test_execute_node_streams_live_when_no_research_tools_used():
    """Regression guard: a heavy turn that did NOT use research tools (e.g. a
    code task) keeps pre-O.3 behavior -- closing synthesis streams live,
    verify_draft stays None. The loop's own clean-stop text ("no tools
    needed") is still suppressed by the O.1-residual fix regardless -- only
    the closing synthesis is ever user-visible for heavy turns."""
    state = _state(difficulty="heavy", needs_agent=True)
    dispatched = []

    async def fake_dispatch(name, data):
        dispatched.append((name, data))

    fake = _fake_stream_with_tools([("no tools needed", None), ("Live answer.", None)])

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake):
        with patch("app.agent.graph.adispatch_custom_event", side_effect=fake_dispatch):
            res = await execute_node(state)

    assert res["verify_draft"] is None
    token_deltas = [data["delta"] for name, data in dispatched if name == "token"]
    assert "".join(token_deltas) == "Live answer."  # NOT "no tools needed" + "Live answer."


@pytest.mark.asyncio
async def test_verify_node_pass_emits_draft_and_stops():
    state = _state(difficulty="heavy", verify_draft="A complete, sourced answer.", revision_count=0)
    dispatched = []

    async def fake_dispatch(name, data):
        dispatched.append((name, data))

    async def fake_complete(*args, **kwargs):
        return {"content": "PASS", "usage": {"total_tokens": 20}}

    with patch("app.core.normalize.chat_complete", side_effect=fake_complete):
        with patch("app.agent.graph.adispatch_custom_event", side_effect=fake_dispatch):
            res = await verify_node(state)

    assert res["needs_revision"] is False
    assert ("token", {"delta": "A complete, sourced answer."}) in dispatched
    assert any(name == "step" and data.get("label") == "Verification passed" for name, data in dispatched)


@pytest.mark.asyncio
async def test_verify_node_gaps_found_nudges_and_loops_back():
    state = _state(
        difficulty="heavy", verify_draft="An incomplete answer.", revision_count=0,
        messages=[{"role": "user", "content": "research X and Y"}],
    )
    dispatched = []

    async def fake_dispatch(name, data):
        dispatched.append((name, data))

    async def fake_complete(*args, **kwargs):
        return {"content": "1. Missing Y's figures entirely.", "usage": {"total_tokens": 20}}

    with patch("app.core.normalize.chat_complete", side_effect=fake_complete):
        with patch("app.agent.graph.adispatch_custom_event", side_effect=fake_dispatch):
            res = await verify_node(state)

    assert res["needs_revision"] is True
    assert res["revision_count"] == 1
    assert not any(name == "token" for name, data in dispatched)  # rejected draft never shown
    assert res["messages"][-1]["role"] == "system"
    assert "Missing Y's figures" in res["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_verify_node_stops_at_max_revisions_without_another_llm_call():
    state = _state(difficulty="heavy", verify_draft="Still imperfect.", revision_count=VERIFY_MAX_REVISIONS)
    dispatched = []

    async def fake_dispatch(name, data):
        dispatched.append((name, data))

    with patch("app.core.normalize.chat_complete", new=AsyncMock()) as mock_complete:
        with patch("app.agent.graph.adispatch_custom_event", side_effect=fake_dispatch):
            res = await verify_node(state)

    mock_complete.assert_not_called()  # budget spent -- don't pay for a check we won't act on
    assert res["needs_revision"] is False
    assert ("token", {"delta": "Still imperfect."}) in dispatched


@pytest.mark.asyncio
async def test_verify_node_upstream_failure_accepts_draft_gracefully():
    state = _state(difficulty="heavy", verify_draft="Draft under a flaky provider.", revision_count=0)
    dispatched = []

    async def fake_dispatch(name, data):
        dispatched.append((name, data))

    async def failing_complete(*args, **kwargs):
        raise RuntimeError("upstream down")

    with patch("app.core.normalize.chat_complete", side_effect=failing_complete):
        with patch("app.agent.graph.adispatch_custom_event", side_effect=fake_dispatch):
            res = await verify_node(state)  # must not raise

    assert res["needs_revision"] is False
    assert ("token", {"delta": "Draft under a flaky provider."}) in dispatched


@pytest.mark.asyncio
async def test_verify_node_empty_draft_and_no_prior_content_falls_back_to_apology():
    """F-7 defense-in-depth: an empty verify_draft with nothing else streamed
    this turn (state["final_answer"] also empty) must never silently
    dispatch zero token events -- that's the exact half-generation/
    empty-reply bug. Falls back to a plain apology instead."""
    state = _state(difficulty="heavy", verify_draft="", revision_count=0, final_answer="")
    dispatched = []

    async def fake_dispatch(name, data):
        dispatched.append((name, data))

    async def fake_complete(*args, **kwargs):
        return {"content": "PASS", "usage": {"total_tokens": 20}}

    with patch("app.core.normalize.chat_complete", side_effect=fake_complete):
        with patch("app.agent.graph.adispatch_custom_event", side_effect=fake_dispatch):
            res = await verify_node(state)

    assert res["needs_revision"] is False
    token_deltas = [data["delta"] for name, data in dispatched if name == "token"]
    assert len(token_deltas) == 1
    assert token_deltas[0]  # non-empty apology, not a silent no-op


@pytest.mark.asyncio
async def test_verify_node_empty_draft_but_prior_content_already_shown_stays_silent():
    """The flip side: if state["final_answer"] already has content (streamed
    live earlier this turn), an empty draft correctly means "nothing more to
    add" -- must NOT re-dispatch final_answer (would duplicate it) or a
    fallback apology (would append a spurious extra message)."""
    state = _state(difficulty="heavy", verify_draft="", revision_count=0, final_answer="already shown live")
    dispatched = []

    async def fake_dispatch(name, data):
        dispatched.append((name, data))

    async def fake_complete(*args, **kwargs):
        return {"content": "PASS", "usage": {"total_tokens": 20}}

    with patch("app.core.normalize.chat_complete", side_effect=fake_complete):
        with patch("app.agent.graph.adispatch_custom_event", side_effect=fake_dispatch):
            res = await verify_node(state)

    assert res["needs_revision"] is False
    assert not any(name == "token" for name, data in dispatched)


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
