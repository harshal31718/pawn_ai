import json
import pytest
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient

from app.main import app
from app.storage import conversations as storage
from app.constants import MEMORY_DB, MEMORY_DIR, CONVERSATIONS_DIR
from app.memory.index import init_db, add_chunk, get_db_connection
from app.memory.retrieve import retrieve

@pytest.fixture(autouse=True)
def clean_memory_and_conversations():
    # Make sure we wipe files before and after tests
    if MEMORY_DIR.exists():
        import shutil
        shutil.rmtree(MEMORY_DIR)
    if CONVERSATIONS_DIR.exists():
        import shutil
        shutil.rmtree(CONVERSATIONS_DIR)
        
    init_db()
    
    yield
    
    if MEMORY_DIR.exists():
        import shutil
        shutil.rmtree(MEMORY_DIR)
    if CONVERSATIONS_DIR.exists():
        import shutil
        shutil.rmtree(CONVERSATIONS_DIR)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_index_and_retrieve_vector():
    """Verify that added chunks are correctly stored and retrieved based on vector similarity."""
    # Insert chunks with mock 768-dim embeddings
    emb_a = [1.0] + [0.0] * 767
    emb_b = [0.0] + [1.0] + [0.0] * 766
    
    add_chunk("conv-A", "Pineapples are a delicious tropical fruit.", emb_a)
    add_chunk("conv-B", "Fast database vector search query execution.", emb_b)
    
    # Retrieve mock queries
    async def mock_embed_a(text):
        return emb_a
        
    async def mock_embed_b(text):
        return emb_b

    # 1. Query matching A
    with patch("app.memory.retrieve.embed", side_effect=mock_embed_a):
        import asyncio
        hits = asyncio.run(retrieve("something tropical"))
        assert len(hits) >= 1
        assert "Pineapples" in hits[0]["text"]
        
    # 2. Query matching B
    with patch("app.memory.retrieve.embed", side_effect=mock_embed_b):
        import asyncio
        hits = asyncio.run(retrieve("database execution"))
        assert len(hits) >= 1
        assert "database vector" in hits[0]["text"]


def test_retrieve_filters_active_conversation():
    """RAG search should exclude the current active conversation context to avoid duplication."""
    emb = [1.0] + [0.0] * 767
    add_chunk("active-conv", "This is in the active thread.", emb)
    add_chunk("other-conv", "This is in an older thread.", emb)
    
    async def mock_embed(text):
        return emb
        
    with patch("app.memory.retrieve.embed", side_effect=mock_embed):
        import asyncio
        hits = asyncio.run(retrieve("thread info", active_conv_id="active-conv"))
        
        # Should only return the old thread since active-conv is filtered out
        for hit in hits:
            assert hit["conv_id"] != "active-conv"
            
        assert len(hits) == 1
        assert hits[0]["conv_id"] == "other-conv"


def test_fts5_fallback_when_embedding_fails():
    """If embedding generation fails, retrieval must gracefully fallback to keyword search (FTS5)."""
    # Insert standard metadata
    emb = [1.0] + [0.0] * 767
    add_chunk("conv-A", "UniqueKeywordHere is a special token.", emb)
    
    # Mock embed to raise exception
    async def mock_embed_fail(text):
        raise Exception("API key expired")
        
    with patch("app.memory.retrieve.embed", side_effect=mock_embed_fail):
        import asyncio
        # Retrieval should still succeed and match keyword
        hits = asyncio.run(retrieve("UniqueKeywordHere"))
        assert len(hits) == 1
        assert "UniqueKeywordHere" in hits[0]["text"]


def test_chat_yields_memory_hit_events(client):
    """If retrieve() returns hits, the chat endpoint must stream memory_hit SSE events."""
    # Create the active conversation to avoid 404
    storage.create_conversation(conv_id="active-conv")
    
    emb = [1.0] + [0.0] * 767
    add_chunk("past-conv", "Remember that Bob loves blue cheese.", emb)
    
    async def mock_embed(text):
        return emb

    async def mock_stream(*args, **kwargs):
        yield "Response"
        
    with patch("app.memory.retrieve.embed", side_effect=mock_embed):
        with patch("app.core.normalize.stream_llm", side_effect=mock_stream):
            with client.stream(
                "POST",
                "/chat",
                json={
                    "messages": [{"role": "user", "content": "What cheese does Bob like?"}],
                    "conversation_id": "active-conv"
                }
            ) as resp:
                body = resp.read().decode()
                
    # Extract events
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:].strip()))
            
    # Should see a memory_hit event containing the Bob memory chunk
    memory_hits = [e for e in events if e.get("type") == "memory_hit"]
    assert len(memory_hits) == 1
    assert "Bob loves blue cheese" in memory_hits[0]["summary"]
