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


def test_chat_streams_tokens(client):
    with patch("app.routes.chat.llm_core.stream_llm", side_effect=mock_stream):
        with client.stream(
            "POST",
            "/chat",
            json={"messages": [{"role": "user", "content": "hi there"}]},
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            body = resp.read().decode()

    assert "data: Hello\n\n" in body
    assert "data: world\n\n" in body
    assert "data: [DONE]\n\n" in body


def test_chat_empty_messages(client):
    with patch("app.routes.chat.llm_core.stream_llm", side_effect=mock_stream):
        with client.stream(
            "POST",
            "/chat",
            json={"messages": []},
        ) as resp:
            assert resp.status_code == 200
            body = resp.read().decode()

    assert "data: [DONE]\n\n" in body
