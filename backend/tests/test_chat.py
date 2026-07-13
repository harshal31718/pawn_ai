import json
import pytest
from unittest.mock import patch, AsyncMock
from starlette.testclient import TestClient

from app.main import app
from app.routes.chat import _build_trace
from app.storage import conversations_drive
from tests.fake_drive import FakeDriveStorage

# Must match conftest.TEST_USER_ID
TEST_USER_ID = "test-user-id"


async def mock_stream(*args, **kwargs):
    for token in ["Hello", ", ", "world", "!"]:
        yield token


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def fake_drive():
    return FakeDriveStorage()


@pytest.fixture()
def drive_client(fake_drive):
    with patch("app.core.drive_factory.get_drive_for_user", return_value=fake_drive):
        with TestClient(app) as c:
            yield c


def _parse_sse_events(body: str) -> list[dict]:
    """Extract parsed JSON objects from an SSE body string."""
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            raw = line[6:].strip()
            try:
                events.append(json.loads(raw))
            except json.JSONDecodeError:
                pass
    return events


# ─── Step 7: Typed SSE events ────────────────────────────────────────────────

def test_chat_streams_typed_token_events(client):
    """Each streamed token must arrive as {"type": "token", "delta": "..."}."""
    with patch("app.core.normalize.stream_llm", side_effect=mock_stream):
        with client.stream(
            "POST",
            "/chat",
            json={"messages": [{"role": "user", "content": "hi there"}]},
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            body = resp.read().decode()

    events = _parse_sse_events(body)
    token_events = [e for e in events if e.get("type") == "token"]
    done_events  = [e for e in events if e.get("type") == "done"]

    assert len(token_events) == 4
    assert token_events[0] == {"type": "token", "delta": "Hello"}
    assert token_events[2] == {"type": "token", "delta": "world"}

    assert len(done_events) == 1
    assert done_events[0]["type"] == "done"
    assert "via_provider" in done_events[0]


def test_chat_no_raw_token_strings(client):
    """Raw token strings must NOT appear — only JSON event objects."""
    with patch("app.core.normalize.stream_llm", side_effect=mock_stream):
        with client.stream(
            "POST",
            "/chat",
            json={"messages": [{"role": "user", "content": "hi"}]},
        ) as resp:
            body = resp.read().decode()

    assert "data: Hello\n" not in body
    assert "data: [DONE]\n" not in body
    assert "data: ERROR:" not in body


def test_chat_sse_response_headers(client):
    """SSE response must carry the correct headers."""
    with patch("app.core.normalize.stream_llm", side_effect=mock_stream):
        with client.stream(
            "POST",
            "/chat",
            json={"messages": [{"role": "user", "content": "hi"}]},
        ) as resp:
            assert resp.headers.get("x-accel-buffering") == "no"
            assert resp.headers.get("cache-control") == "no-cache"
            resp.read()


def test_chat_empty_messages(client):
    """Empty message list must still produce a done event."""
    with patch("app.core.normalize.stream_llm", side_effect=mock_stream):
        with client.stream(
            "POST",
            "/chat",
            json={"messages": []},
        ) as resp:
            assert resp.status_code == 200
            body = resp.read().decode()

    events = _parse_sse_events(body)
    done_events = [e for e in events if e.get("type") == "done"]
    assert len(done_events) == 1


# ─── Step 8: Conversation history ────────────────────────────────────────────

def test_chat_forwards_full_history(client):
    """Backend must forward the complete message array to the LLM, not just the last turn."""
    captured_messages: list = []

    async def capturing_stream(url, model, messages, headers):
        captured_messages.extend(messages)
        yield "ok"

    with patch("app.core.normalize.stream_llm", side_effect=capturing_stream):
        history = [
            {"role": "user",      "content": "my name is Priya"},
            {"role": "assistant", "content": "Nice to meet you Priya!"},
            {"role": "user",      "content": "what is my name?"},
        ]
        with client.stream("POST", "/chat", json={"messages": history}) as resp:
            assert resp.status_code == 200
            resp.read()

    # Short/plain text -> classify() routes to direct_answer (Phase A / A.6):
    # one streaming call forwarding the full history verbatim, no extra prompts.
    assert len(captured_messages) == 3
    assert captured_messages[0]["content"] == "my name is Priya"
    assert captured_messages[1]["role"] == "assistant"
    assert captured_messages[2]["content"] == "what is my name?"


# ─── Step 9: Multi-provider (normalize.py routing) ───────────────────────────

def test_chat_defaults_to_gemini(client):
    """When no provider is given, the request uses gemini (the default)."""
    captured_urls: list = []

    async def capturing_stream(url, model, messages, headers):
        captured_urls.append(url)
        yield "ok"

    with patch("app.core.normalize.stream_llm", side_effect=capturing_stream):
        with client.stream(
            "POST", "/chat",
            json={"messages": [{"role": "user", "content": "hi"}]},
        ) as resp:
            resp.read()

    # Short/plain text -> classify() routes to direct_answer: one streaming call.
    assert len(captured_urls) == 1
    assert "generativelanguage" in captured_urls[0]


def test_chat_routes_to_groq(client):
    """provider='groq' must route to the Groq API endpoint."""
    captured_urls: list = []

    async def capturing_stream(url, model, messages, headers):
        captured_urls.append(url)
        yield "ok"

    with patch("app.core.normalize.stream_llm", side_effect=capturing_stream):
        with client.stream(
            "POST", "/chat",
            json={"messages": [{"role": "user", "content": "hi"}], "provider": "groq"},
        ) as resp:
            resp.read()

    # Short/plain text -> classify() routes to direct_answer: one streaming call.
    assert len(captured_urls) == 1
    assert "groq.com" in captured_urls[0]


def test_chat_routes_to_cerebras(client):
    """provider='cerebras' must route to the Cerebras API endpoint."""
    captured_urls: list = []

    async def capturing_stream(url, model, messages, headers):
        captured_urls.append(url)
        yield "ok"

    with patch("app.core.normalize.stream_llm", side_effect=capturing_stream):
        with client.stream(
            "POST", "/chat",
            json={"messages": [{"role": "user", "content": "hi"}], "provider": "cerebras"},
        ) as resp:
            resp.read()

    # Short/plain text -> classify() routes to direct_answer: one streaming call.
    assert len(captured_urls) == 1
    assert "cerebras.ai" in captured_urls[0]


def test_chat_unknown_provider_returns_error_event(client):
    """An unknown provider must produce an SSE error event, not a 500."""
    with client.stream(
        "POST", "/chat",
        json={"messages": [{"role": "user", "content": "hi"}], "provider": "nonexistent"},
    ) as resp:
        assert resp.status_code == 200   # SSE always 200 — errors are in the stream
        body = resp.read().decode()

    events = _parse_sse_events(body)
    error_events = [e for e in events if e.get("type") == "error"]
    assert len(error_events) == 1
    assert "nonexistent" in error_events[0]["message"]


def test_chat_done_event_carries_provider_name(client):
    """done event must carry the via_provider field matching the selected provider."""
    with patch("app.core.normalize.stream_llm", side_effect=mock_stream):
        with client.stream(
            "POST", "/chat",
            json={"messages": [{"role": "user", "content": "hi"}], "provider": "groq"},
        ) as resp:
            body = resp.read().decode()

    events = _parse_sse_events(body)
    done = next(e for e in events if e.get("type") == "done")
    assert done["via_provider"] == "groq"


# ─── Phase A / A.8: trace persistence ────────────────────────────────────────

def test_build_trace_maps_tool_log_and_citations():
    tool_log = [
        {"name": "web_search", "args": {"query": "x"}, "observation": "results", "elapsed_ms": 120, "agent": "main"},
        {"name": "fetch_url", "args": {"url": "https://a.com"}, "observation": "page text", "elapsed_ms": 300, "agent": "researcher"},
    ]
    citations = [{"url": "https://a.com", "title": "A"}]

    trace = _build_trace(tool_log, citations)

    assert trace[0] == {
        "kind": "tool", "agent": "main", "name": "web_search",
        "args": {"query": "x"}, "observation": "results", "elapsed_ms": 120,
    }
    assert trace[1]["agent"] == "researcher"
    assert trace[2] == {"kind": "citation", "agent": "main", "url": "https://a.com", "title": "A"}


def test_build_trace_empty_input_yields_empty_trace():
    assert _build_trace([], []) == []


def test_build_trace_caps_at_trace_max_entries():
    from app.constants import TRACE_MAX_ENTRIES

    tool_log = [
        {"name": "get_datetime", "args": {}, "observation": str(i), "elapsed_ms": 1, "agent": "main"}
        for i in range(TRACE_MAX_ENTRIES + 10)
    ]
    trace = _build_trace(tool_log, [])
    assert len(trace) == TRACE_MAX_ENTRIES
    # Oldest dropped -- the surviving entries are the most recent ones.
    assert trace[0]["observation"] == "10"
    assert trace[-1]["observation"] == str(TRACE_MAX_ENTRIES + 9)


def test_chat_direct_answer_path_persists_no_trace_field(drive_client, fake_drive):
    """A light 'hello'-shaped message takes the direct-answer fast path --
    tool_log/citations never populate, so no `trace` key should be persisted
    at all (absent field = no trace, not an empty list)."""
    conv_id = "conv-direct-1"

    with patch("app.core.normalize.stream_llm", side_effect=mock_stream):
        with drive_client.stream(
            "POST", "/chat",
            json={"messages": [{"role": "user", "content": "hi"}], "conversation_id": conv_id},
        ) as resp:
            assert resp.status_code == 200
            resp.read()

    messages = conversations_drive.load_messages(fake_drive, conv_id)
    assistant_msg = next(m for m in messages if m["role"] == "assistant")
    assert "trace" not in assistant_msg


def test_chat_agent_path_persists_tool_trace(drive_client, fake_drive):
    """Force the heavy/agent path via a tool call and confirm the persisted
    assistant record's `trace` field reflects the graph's final tool_log."""
    conv_id = "conv-agent-1"
    call_count = {"n": 0}

    async def fake_complete(model_id, messages, resolver, rate_limiter, user_id=None, tools=None, tool_choice="auto"):
        call_count["n"] += 1
        if tool_choice == "none":
            return {"role": "assistant", "content": "1. Use the calculator", "usage": {"total_tokens": 5}}
        if call_count["n"] <= 2:
            return {
                "role": "assistant", "content": "", "usage": {"total_tokens": 5},
                "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "calculator", "arguments": '{"expression": "2+2"}'}}],
            }
        return {"role": "assistant", "content": "the answer is 4", "tool_calls": None, "usage": {"total_tokens": 5}}

    async def fake_stream(*args, **kwargs):
        yield "the answer is 4"

    with patch("app.agent.graph.router_classify", new=AsyncMock(return_value={"difficulty": "heavy", "needs_agent": True})):
        with patch("app.core.normalize.chat_complete", side_effect=fake_complete):
            with patch("app.core.normalize.chat_stream", side_effect=fake_stream):
                with drive_client.stream(
                    "POST", "/chat",
                    json={"messages": [{"role": "user", "content": "please analyze this deeply"}], "conversation_id": conv_id},
                ) as resp:
                    assert resp.status_code == 200
                    resp.read()

    messages = conversations_drive.load_messages(fake_drive, conv_id)
    assistant_msg = next(m for m in messages if m["role"] == "assistant")
    assert "trace" in assistant_msg
    tool_entries = [t for t in assistant_msg["trace"] if t["kind"] == "tool"]
    assert len(tool_entries) >= 1
    assert tool_entries[0]["name"] == "calculator"
    assert tool_entries[0]["observation"] == "4"
    assert tool_entries[0]["agent"] == "main"
    assert "elapsed_ms" in tool_entries[0]


def test_chat_agent_path_persists_top_level_citations(drive_client, fake_drive):
    """Regression: the persisted assistant record must carry a top-level
    `citations` field, not just citation entries folded into `trace` — the
    frontend's CitationChips read message.citations directly and never derive
    it from trace, so without this a real reload (not the live SSE session)
    silently loses source chips even though the trace still has them."""
    conv_id = "conv-agent-citations-1"
    call_count = {"n": 0}

    async def fake_complete(model_id, messages, resolver, rate_limiter, user_id=None, tools=None, tool_choice="auto"):
        call_count["n"] += 1
        if tool_choice == "none":
            return {"role": "assistant", "content": "1. Fetch the page", "usage": {"total_tokens": 5}}
        if call_count["n"] <= 2:
            return {
                "role": "assistant", "content": "", "usage": {"total_tokens": 5},
                "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "fetch_url", "arguments": '{"url": "https://example.com/article"}'}}],
            }
        return {"role": "assistant", "content": "summarized", "tool_calls": None, "usage": {"total_tokens": 5}}

    async def fake_stream(*args, **kwargs):
        yield "summarized"

    with patch("app.agent.graph.router_classify", new=AsyncMock(return_value={"difficulty": "heavy", "needs_agent": True})):
        with patch("app.core.normalize.chat_complete", side_effect=fake_complete):
            with patch("app.core.normalize.chat_stream", side_effect=fake_stream):
                with patch("app.agent.graph.run_tool", new=AsyncMock(return_value="fetched page text")):
                    with drive_client.stream(
                        "POST", "/chat",
                        json={"messages": [{"role": "user", "content": "summarize this article deeply"}], "conversation_id": conv_id},
                    ) as resp:
                        assert resp.status_code == 200
                        resp.read()

    messages = conversations_drive.load_messages(fake_drive, conv_id)
    assistant_msg = next(m for m in messages if m["role"] == "assistant")
    assert assistant_msg.get("citations") == [{"url": "https://example.com/article", "title": "https://example.com/article"}]
    citation_trace_entries = [t for t in assistant_msg["trace"] if t["kind"] == "citation"]
    assert citation_trace_entries == [{"kind": "citation", "agent": "main", "url": "https://example.com/article", "title": "https://example.com/article"}]
