import json
import pytest
from unittest.mock import patch, MagicMock

from starlette.testclient import TestClient
from app.main import app
from app.storage import conversations as storage
from app.constants import CONVERSATIONS_DIR
from app.memory.summarize import summarize_history

@pytest.fixture()
def client():
    if CONVERSATIONS_DIR.exists():
        import shutil
        shutil.rmtree(CONVERSATIONS_DIR)
        
    with TestClient(app) as c:
        yield c
        
    if CONVERSATIONS_DIR.exists():
        import shutil
        shutil.rmtree(CONVERSATIONS_DIR)


def test_summarize_history_direct():
    """Directly test summarize_history to verify it maps LLM tokens into a summary string."""
    async def mock_chat_stream(*args, **kwargs):
        for token in ["Summary", " bullets", " here."]:
            yield token

    with patch("app.memory.summarize.chat_stream", side_effect=mock_chat_stream):
        import asyncio
        summary = asyncio.run(summarize_history([{"role": "user", "content": "hi"}]))
        assert summary == "Summary bullets here."


def test_chat_truncates_context_to_last_10_messages(client):
    """When loading history, context must truncate to the last 10 messages."""
    meta = storage.create_conversation(title="Long Chat")
    conv_id = meta["id"]
    
    # Write 12 historical messages (6 turns)
    history = []
    for i in range(6):
        history.append({"role": "user", "content": f"User prompt {i}"})
        history.append({"role": "assistant", "content": f"Assistant response {i}"})
    storage.append_messages(conv_id, history)
    
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
                "conversation_id": conv_id
            }
        ) as resp:
            resp.read()

    # 1 planning prompt + 10 history + 1 user prompt + 1 synthesis prompt = 13 messages
    assert len(captured_messages) == 13
    assert captured_messages[1]["content"] == "User prompt 1"
    assert captured_messages[-2]["content"] == "Latest turn?"


def test_chat_prepends_summary_context(client):
    """If summary.md exists for a conversation, it must be injected as a system prompt."""
    meta = storage.create_conversation(title="Chat with Summary")
    conv_id = meta["id"]
    
    # Save a summary
    storage.save_summary(conv_id, "Summary text showing user name is Bob.")
    
    # Append a history message
    storage.append_messages(conv_id, [{"role": "user", "content": "hi"}])
    
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
                "conversation_id": conv_id
            }
        ) as resp:
            resp.read()
            
    # Messages in final call should be:
    # 1: Summary System Message
    # 2: User prompt from history ("hi")
    # 3: Latest prompt ("What is my name?")
    # 4: Synthesis prompt
    assert len(captured_messages) == 5
    assert captured_messages[1]["role"] == "system"
    assert "Summary text showing user name is Bob." in captured_messages[1]["content"]
    assert captured_messages[2]["content"] == "hi"
    assert captured_messages[3]["content"] == "What is my name?"


def test_chat_triggers_summarize_background_task_at_20_messages(client):
    """Summarization task must be enqueued when message count becomes a multiple of 20."""
    meta = storage.create_conversation(title="Threshold Chat")
    conv_id = meta["id"]
    
    # Create 18 historical messages (so sending 1 more user prompt + assistant response makes it 20)
    history = []
    for i in range(9):
        history.append({"role": "user", "content": f"prompt {i}"})
        history.append({"role": "assistant", "content": f"response {i}"})
    storage.append_messages(conv_id, history)
    
    async def mock_stream(*args, **kwargs):
        yield "AI reply"
        
    with patch("app.core.normalize.stream_llm", side_effect=mock_stream):
        with patch("app.routes.chat.summarize_conversation_task") as mock_summarize:
            with client.stream(
                "POST",
                "/chat",
                json={
                    "messages": [{"role": "user", "content": "Make it 20"}],
                    "conversation_id": conv_id
                }
            ) as resp:
                resp.read()
                
            # Starlette TestClient runs background tasks synchronous before exiting the context manager.
            # So the task should have been enqueued and called.
            mock_summarize.assert_called_once_with(conv_id)
