import json
import pytest
from unittest.mock import patch
from starlette.testclient import TestClient

from app.main import app
from app.storage import conversations_drive as storage
from app.memory.summarize import summarize_history
from tests.fake_drive import FakeDriveStorage

# Must match conftest.TEST_USER_ID
TEST_USER_ID = "test-user-id"


@pytest.fixture()
def fake_drive():
    return FakeDriveStorage()


@pytest.fixture()
def client(fake_drive):
    with patch("app.core.drive_factory.get_drive_for_user", return_value=fake_drive):
        with TestClient(app) as c:
            yield c


def test_summarize_history_direct():
    """Directly test summarize_history to verify it maps LLM tokens into a summary string."""
    async def mock_chat_stream(*args, **kwargs):
        for token in ["Summary", " bullets", " here."]:
            yield token

    with patch("app.memory.summarize.chat_stream", side_effect=mock_chat_stream):
        import asyncio
        summary = asyncio.run(summarize_history([{"role": "user", "content": "hi"}]))
        assert summary == "Summary bullets here."


def test_chat_truncates_context_to_last_10_messages(client, fake_drive):
    """When loading history, context must truncate to the last 10 messages."""
    meta = storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="Long Chat")
    conv_id = meta["id"]

    history = []
    for i in range(6):
        history.append({"role": "user", "content": f"User prompt {i}"})
        history.append({"role": "assistant", "content": f"Assistant response {i}"})
    storage.append_messages(fake_drive, conv_id, history)

    captured_messages = []

    async def capturing_stream(url, model, messages, headers):
        captured_messages.extend(messages)
        yield "Response"

    with patch("app.core.normalize.stream_llm", side_effect=capturing_stream):
        with client.stream(
            "POST",
            "/chat",
            json={
                "messages": [{"role": "user", "content": "Latest turn?"}],
                "conversation_id": conv_id,
            },
        ) as resp:
            resp.read()

    # 1 planning prompt + 10 history + 1 user prompt + 1 synthesis prompt = 13
    assert len(captured_messages) == 13
    assert captured_messages[1]["content"] == "User prompt 1"
    assert captured_messages[-2]["content"] == "Latest turn?"


def test_chat_prepends_summary_context(client, fake_drive):
    """If summary.md exists for a conversation, it must be injected as a system prompt."""
    meta = storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="Chat with Summary")
    conv_id = meta["id"]

    storage.save_summary(fake_drive, conv_id, "Summary text showing user name is Bob.")
    storage.append_messages(fake_drive, conv_id, [{"role": "user", "content": "hi"}])

    captured_messages = []

    async def capturing_stream(url, model, messages, headers):
        captured_messages.extend(messages)
        yield "Response"

    with patch("app.core.normalize.stream_llm", side_effect=capturing_stream):
        with client.stream(
            "POST",
            "/chat",
            json={
                "messages": [{"role": "user", "content": "What is my name?"}],
                "conversation_id": conv_id,
            },
        ) as resp:
            resp.read()

    # Messages: 1 planning + summary system + hi + What is my name? + synthesis = 5
    assert len(captured_messages) == 5
    assert captured_messages[1]["role"] == "system"
    assert "Summary text showing user name is Bob." in captured_messages[1]["content"]
    assert captured_messages[2]["content"] == "hi"
    assert captured_messages[3]["content"] == "What is my name?"


def test_chat_triggers_summarize_background_task_at_20_messages(client, fake_drive):
    """Summarization task must be enqueued when message count becomes a multiple of 20."""
    meta = storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="Threshold Chat")
    conv_id = meta["id"]

    history = []
    for i in range(9):
        history.append({"role": "user", "content": f"prompt {i}"})
        history.append({"role": "assistant", "content": f"response {i}"})
    storage.append_messages(fake_drive, conv_id, history)

    async def mock_stream(*args, **kwargs):
        yield "AI reply"

    with patch("app.core.normalize.stream_llm", side_effect=mock_stream):
        with patch("app.routes.chat.summarize_conversation_task") as mock_summarize:
            with client.stream(
                "POST",
                "/chat",
                json={
                    "messages": [{"role": "user", "content": "Make it 20"}],
                    "conversation_id": conv_id,
                },
            ) as resp:
                resp.read()

            mock_summarize.assert_called_once()
            assert mock_summarize.call_args[0][0] == conv_id


def test_summarize_conversation_task_skips_when_drive_unavailable():
    """No local fallback anymore — the background task must silently skip
    (not crash) when Drive isn't available for the user."""
    from app.memory.summarize import summarize_conversation_task
    import asyncio

    with patch("app.core.drive_factory.get_drive_for_user", return_value=None):
        # Must not raise.
        asyncio.run(summarize_conversation_task("conv-x", user_id=TEST_USER_ID))
