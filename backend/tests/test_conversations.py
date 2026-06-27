import json
import pytest
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient

from app.main import app
from app.storage import conversations as storage
from app.constants import CONVERSATIONS_DIR

@pytest.fixture()
def client():
    # Make sure CONVERSATIONS_DIR is cleared before and after tests
    if CONVERSATIONS_DIR.exists():
        import shutil
        shutil.rmtree(CONVERSATIONS_DIR)
        
    with TestClient(app) as c:
        yield c
        
    if CONVERSATIONS_DIR.exists():
        import shutil
        shutil.rmtree(CONVERSATIONS_DIR)


def test_crud_endpoints(client):
    """Verify that conversations can be created, listed, fetched, updated, and deleted."""
    # 1. List (empty)
    resp = client.get("/conversations")
    assert resp.status_code == 200
    assert resp.json() == []
    
    # 2. Create
    resp = client.post("/conversations", json={"title": "Test Chat", "model_id": "gemini"})
    assert resp.status_code == 200
    meta = resp.json()
    assert meta["title"] == "Test Chat"
    assert meta["model_id"] == "gemini"
    assert "id" in meta
    conv_id = meta["id"]
    
    # 3. List (one item)
    resp = client.get("/conversations")
    assert resp.status_code == 200
    lst = resp.json()
    assert len(lst) == 1
    assert lst[0]["id"] == conv_id
    
    # 4. Fetch detail
    resp = client.get(f"/conversations/{conv_id}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["meta"]["id"] == conv_id
    assert detail["messages"] == []
    
    # 5. Patch title
    resp = client.patch(f"/conversations/{conv_id}", json={"title": "Updated Chat Title"})
    assert resp.status_code == 200
    meta = resp.json()
    assert meta["title"] == "Updated Chat Title"
    
    # 6. Fetch to verify patch
    resp = client.get(f"/conversations/{conv_id}")
    assert resp.json()["meta"]["title"] == "Updated Chat Title"
    
    # 7. Delete
    resp = client.delete(f"/conversations/{conv_id}")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    
    # 8. Fetch returns 404
    resp = client.get(f"/conversations/{conv_id}")
    assert resp.status_code == 404


def test_chat_persistence_saves_to_disk(client):
    """When a chat has conversation_id, messages must be saved to messages.jsonl."""
    # Create conversation first
    meta = storage.create_conversation(title="Active Chat")
    conv_id = meta["id"]
    
    async def mock_stream(*args, **kwargs):
        yield "Response"
        yield " from"
        yield " AI."

    with patch("app.core.normalize.stream_llm", side_effect=mock_stream):
        with client.stream(
            "POST",
            "/chat",
            json={
                "messages": [{"role": "user", "content": "How are you?"}],
                "conversation_id": conv_id
            }
        ) as resp:
            resp.read()
            
    # Load messages and check if they are saved to disk
    messages = storage.load_messages(conv_id)
    assert len(messages) == 2
    assert messages[0] == {"role": "user", "content": "How are you?"}
    assert messages[1] == {"role": "assistant", "content": "Response from AI."}
    
    # Check meta message_count updated
    meta_updated = storage.get_conversation_meta(conv_id)
    assert meta_updated["message_count"] == 2


def test_chat_auto_titling_trigger(client):
    """The first response to a 'New Chat' must trigger auto-titling background task."""
    meta = storage.create_conversation(title="New Chat")
    conv_id = meta["id"]
    
    async def mock_stream(*args, **kwargs):
        # The mock model returns "Generated Title Output" when prompted
        for token in ["Generated", " Title", " Output"]:
            yield token

    with patch("app.core.normalize.stream_llm", side_effect=mock_stream):
        with client.stream(
            "POST",
            "/chat",
            json={
                "messages": [{"role": "user", "content": "My prompt here"}],
                "conversation_id": conv_id
            }
        ) as resp:
            resp.read()
            
    # Check that metadata title got updated
    updated_meta = storage.get_conversation_meta(conv_id)
    assert updated_meta["title"] == "Generated Title Output"

