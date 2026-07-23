"""Tests for the preset subagents (Phase A / A.7): researcher/summarizer/coder,
delegated to via delegate_<name> tools. Delegation is strictly sequential --
these tests exercise run_subagent directly (no create_task/parallelism
anywhere in the implementation) and its wiring into execute_node's tool loop."""

from unittest.mock import AsyncMock, patch

import pytest

from app.agent.graph import DELEGATE_PREFIX as GRAPH_DELEGATE_PREFIX
from app.agent.graph import execute_node
from app.agent.subagents import (
    DELEGATE_PREFIX,
    SUBAGENTS,
    delegate_tool_specs,
    run_subagent,
)
from app.constants import AGENT_MAX_TOKENS, SUBAGENT_MAX_ITERATIONS


class _FakeResolver:
    def pick(self, model_id, user_id=None):
        return [("https://api.google.com", "gemini-2.5-flash", {}, "ep-dummy", "google")]

    def pick_model_by_capability(self, level, visibility="internal", user_id=None, require_tools=False, **kwargs):
        return "gemini-2.5-flash"

    def fallback_models(self, model_id, user_id=None, **kwargs):
        return [model_id]


class _FakeRateLimiter:
    # **kwargs absorbs R2's user_id/token arguments so this fake doesn't have to
    # track the real limiter's signature.
    def can_use(self, endpoint, **kwargs) -> bool:
        return True

    def record_call(self, endpoint_id, token_count=0, **kwargs):
        pass

    def record_tokens(self, endpoint_id, token_count=0, **kwargs):
        pass

    def record_429(self, endpoint_id, retry_after=60, **kwargs):
        pass

    def record_connect_failure(self, endpoint_id, **kwargs):
        pass

    def record_success(self, endpoint_id, **kwargs):
        pass

    def failure_count(self, endpoint_id, **kwargs) -> int:
        return 0

    def usage_pct(self, endpoint, **kwargs) -> float:
        return 0.0


def _ctx(user_id="u1", scope_type=None, scope_id=None):
    from app.agent.tools.base import ToolContext

    return ToolContext(
        user_id=user_id, scope_type=scope_type, scope_id=scope_id,
        resolver=_FakeResolver(), rate_limiter=_FakeRateLimiter(),
    )


# ── structural: no nested delegation, exactly three presets ────────────────

def test_exactly_three_presets():
    assert set(SUBAGENTS.keys()) == {"researcher", "summarizer", "coder"}


def test_no_subagent_exposes_delegate_tools_depth_guard():
    """Structural depth guard (max depth 1): no preset's tools_fn ever
    includes a delegate_* tool, regardless of ctx."""
    ctx = _ctx()
    for name, preset in SUBAGENTS.items():
        tools = preset.tools_fn(ctx)
        assert all(not t.name.startswith(DELEGATE_PREFIX) for t in tools), name


def test_summarizer_and_coder_have_no_tools():
    ctx = _ctx()
    assert SUBAGENTS["summarizer"].tools_fn(ctx) == []
    assert SUBAGENTS["coder"].tools_fn(ctx) == []


def test_researcher_toolset_restricted_to_search_and_fetch():
    ctx = _ctx()
    with patch("app.agent.subagents.key_store.get_key", return_value=None):
        tools = SUBAGENTS["researcher"].tools_fn(ctx)
    names = {t.name for t in tools}
    assert names == {"fetch_url"}  # no search key configured -> web_search absent


def test_researcher_gets_web_search_when_key_configured():
    ctx = _ctx()
    with patch("app.agent.subagents.key_store.get_key", side_effect=lambda uid, provider: "k" if provider == "tavily" else None):
        tools = SUBAGENTS["researcher"].tools_fn(ctx)
    names = {t.name for t in tools}
    assert names == {"fetch_url", "web_search"}


def test_delegate_tool_specs_names_and_shape():
    specs = delegate_tool_specs()
    names = {s["function"]["name"] for s in specs}
    assert names == {"delegate_researcher", "delegate_summarizer", "delegate_coder"}
    for s in specs:
        assert s["type"] == "function"
        assert s["function"]["parameters"]["required"] == ["task"]


# ── run_subagent ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_subagent_unknown_name_is_tool_error():
    res = await run_subagent("nonexistent", "do something", _ctx(), tokens_used=0)
    assert res["result"].startswith("TOOL_ERROR")
    assert res["tool_log"] == []
    assert res["citations"] == []


@pytest.mark.asyncio
async def test_run_subagent_summarizer_no_tool_calls_returns_content():
    async def fake_complete(*args, **kwargs):
        return {"role": "assistant", "content": "Concise summary.", "tool_calls": None, "usage": {"total_tokens": 20}}

    with patch("app.agent.subagents.normalize.chat_complete", side_effect=fake_complete):
        res = await run_subagent("summarizer", "summarize this long text", _ctx(), tokens_used=0)

    assert res["result"] == "Concise summary."
    assert res["tokens_used"] == 20
    assert res["tool_log"] == []


@pytest.mark.asyncio
async def test_run_subagent_researcher_runs_a_tool_call_and_shares_budget():
    call_count = {"n": 0}

    async def fake_complete(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {
                "role": "assistant", "content": "", "usage": {"total_tokens": 30},
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "fetch_url", "arguments": '{"url": "https://example.com"}'}}],
            }
        return {"role": "assistant", "content": "Found X on example.com.", "tool_calls": None, "usage": {"total_tokens": 15}}

    async def fake_run_tool(spec, args, ctx):
        return "page contents about X"

    with patch("app.agent.subagents.normalize.chat_complete", side_effect=fake_complete):
        with patch("app.agent.subagents.run_tool", side_effect=fake_run_tool):
            with patch("app.agent.subagents.adispatch_custom_event", new=AsyncMock()):
                res = await run_subagent("researcher", "research X", _ctx(), tokens_used=100)

    assert res["result"] == "Found X on example.com."
    # Shared budget: 100 (parent's running total) + 30 + 15 = 145.
    assert res["tokens_used"] == 145
    assert len(res["tool_log"]) == 1
    assert res["tool_log"][0]["name"] == "fetch_url"
    assert res["tool_log"][0]["agent"] == "researcher"
    assert res["citations"] == [{"url": "https://example.com", "title": "https://example.com"}]


@pytest.mark.asyncio
async def test_run_subagent_stops_at_max_iterations():
    async def always_calls_tool(*args, **kwargs):
        return {
            "role": "assistant", "content": "", "usage": {},
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "fetch_url", "arguments": '{"url": "https://example.com"}'}}],
        }

    async def fake_run_tool(spec, args, ctx):
        return "some page text"

    with patch("app.agent.subagents.normalize.chat_complete", side_effect=always_calls_tool):
        with patch("app.agent.subagents.run_tool", side_effect=fake_run_tool):
            with patch("app.agent.subagents.adispatch_custom_event", new=AsyncMock()):
                res = await run_subagent("researcher", "research forever", _ctx(), tokens_used=0)

    assert len(res["tool_log"]) == SUBAGENT_MAX_ITERATIONS
    assert "did not conclude within its budget" in res["result"]


@pytest.mark.asyncio
async def test_run_subagent_rejects_a_delegate_shaped_tool_call_at_runtime():
    """Depth guard, enforced structurally: even if a model somehow emits a
    delegate_* tool_call inside a subagent's own loop (e.g. a future preset
    misconfiguration exposing one), run_subagent must reject it rather than
    dispatch it -- max depth 1 is never just "true by omission"."""
    call_count = {"n": 0}

    async def fake_complete(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {
                "role": "assistant", "content": "", "usage": {},
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "delegate_researcher", "arguments": '{"task": "nested"}'}}],
            }
        return {"role": "assistant", "content": "done", "tool_calls": None, "usage": {}}

    with patch("app.agent.subagents.normalize.chat_complete", side_effect=fake_complete):
        with patch("app.agent.subagents.adispatch_custom_event", new=AsyncMock()):
            res = await run_subagent("coder", "write code", _ctx(), tokens_used=0)

    assert res["tool_log"][0]["observation"] == "TOOL_ERROR: subagents cannot delegate further (max depth 1)"


@pytest.mark.asyncio
async def test_run_subagent_respects_already_exhausted_parent_budget():
    with patch("app.agent.subagents.normalize.chat_complete", new=AsyncMock()) as mock_complete:
        res = await run_subagent("summarizer", "summarize", _ctx(), tokens_used=AGENT_MAX_TOKENS)

    mock_complete.assert_not_called()
    assert "did not produce a result" in res["result"]
    assert res["tokens_used"] == AGENT_MAX_TOKENS


@pytest.mark.asyncio
async def test_run_subagent_upstream_failure_never_raises():
    async def failing_complete(*args, **kwargs):
        raise RuntimeError("upstream exploded")

    with patch("app.agent.subagents.normalize.chat_complete", side_effect=failing_complete):
        res = await run_subagent("coder", "write a function", _ctx(), tokens_used=0)  # must not raise

    assert "did not produce a result" in res["result"]


# ── wiring into execute_node (graph.py) ──────────────────────────────────

def test_delegate_prefix_consistent_across_modules():
    assert GRAPH_DELEGATE_PREFIX == DELEGATE_PREFIX == "delegate_"


@pytest.mark.asyncio
async def test_execute_node_delegates_sequentially_and_merges_trace():
    """'research X and summarize' -- main calls delegate_researcher, gets a
    digest back, then stops (no further tool_calls). Verifies: the delegate
    call never goes through the generic run_tool path, the subagent's nested
    tool_log/citations merge into the parent's, and tokens_used accumulates
    across both the parent's own call and the subagent's internal calls."""
    state = {
        "messages": [{"role": "user", "content": "research X and summarize"}],
        "user_id": "u1", "conversation_id": "c1", "user_model_id": "gemini-2.5-flash",
        "has_doc": False, "scope_type": None, "scope_id": None,
        "difficulty": "heavy", "needs_agent": True, "plan": [],
        "tool_log": [], "tokens_used": 0, "citations": [], "final_answer": None,
    }

    main_call_count = {"n": 0}

    async def fake_main_stream(*args, **kwargs):
        main_call_count["n"] += 1
        if main_call_count["n"] == 1:
            yield {
                "type": "done",
                "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "delegate_researcher", "arguments": '{"task": "research X"}'}}],
                "finish_reason": "tool_calls",
                "usage": {"total_tokens": 10},
            }
        elif main_call_count["n"] == 2:
            yield {"type": "content", "delta": "Here is the summary of X."}
            yield {"type": "done", "tool_calls": None, "finish_reason": "stop", "usage": {"total_tokens": 5}}
        else:
            # O.1's mandatory closing-synthesis call (heavy difficulty).
            yield {"type": "content", "delta": " Confirmed."}
            yield {"type": "done", "tool_calls": None, "finish_reason": "stop", "usage": {"total_tokens": 3}}

    async def fake_run_subagent(name, task, ctx, tokens_used):
        assert name == "researcher"
        assert task == "research X"
        return {
            "result": "Researcher's sourced digest about X.",
            "tool_log": [{"name": "fetch_url", "args": {"url": "https://example.com"}, "observation": "X details", "elapsed_ms": 5, "agent": "researcher"}],
            "citations": [{"url": "https://example.com", "title": "https://example.com"}],
            "tokens_used": tokens_used + 42,
        }

    with patch("app.core.normalize.chat_stream_with_tools", side_effect=fake_main_stream):
        with patch("app.agent.graph.run_subagent", side_effect=fake_run_subagent):
            with patch("app.agent.graph.adispatch_custom_event", new=AsyncMock()):
                res = await execute_node(state)

    # Parent tool_log: the delegate_researcher call itself, plus the researcher's
    # own nested fetch_url call merged in right after it.
    assert [t["name"] for t in res["tool_log"]] == ["delegate_researcher", "fetch_url"]
    assert res["tool_log"][0]["observation"] == "Researcher's sourced digest about X."
    assert res["tool_log"][0]["agent"] == "main"
    assert res["tool_log"][1]["agent"] == "researcher"
    assert res["citations"] == [{"url": "https://example.com", "title": "https://example.com"}]
    # 10 (main's plan call) + 5 (main's second call) + 42 (subagent's calls)
    # + 3 (O.1's closing-synthesis call, heavy difficulty) = 60.
    assert res["tokens_used"] == 60
