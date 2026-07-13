import json
import pytest
from unittest.mock import patch, AsyncMock
from starlette.testclient import TestClient

from app.main import app


async def mock_stream(*args, **kwargs):
    for token in ["Hello", ", ", "world", "!"]:
        yield token


@pytest.fixture()
def client():
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
