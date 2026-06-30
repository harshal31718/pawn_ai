"""Tests for the Supabase-backed memory layer (index + retrieve).

The Supabase client is mocked — these tests verify the Python-side orchestration:
correct RPC parameters, RRF fusion, FTS fallback when embedding fails, and the
memory_hit SSE event emission. They do not require a live Supabase instance.
"""

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.storage import conversations as storage
from app.constants import CONVERSATIONS_DIR
from app.memory.index import add_chunk
from app.memory.retrieve import retrieve


@pytest.fixture(autouse=True)
def clean_conversations():
    import shutil

    if CONVERSATIONS_DIR.exists():
        shutil.rmtree(CONVERSATIONS_DIR)
    yield
    if CONVERSATIONS_DIR.exists():
        shutil.rmtree(CONVERSATIONS_DIR)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _fake_db(vec_rows=None, fts_rows=None, insert_id=1):
    """Build a fake Supabase client supporting .table().insert() and .rpc()."""
    db = MagicMock()

    # insert chain: db.table(...).insert(...).execute().data
    insert_exec = MagicMock()
    insert_exec.data = [{"id": insert_id}] if insert_id is not None else []
    db.table.return_value.insert.return_value.execute.return_value = insert_exec

    def rpc_side_effect(fn_name, params):
        rpc_result = MagicMock()
        if fn_name == "match_memory_chunks":
            rpc_result.data = vec_rows or []
        elif fn_name == "search_memory_chunks":
            rpc_result.data = fts_rows or []
        else:
            rpc_result.data = []
        rpc_chain = MagicMock()
        rpc_chain.execute.return_value = rpc_result
        return rpc_chain

    db.rpc.side_effect = rpc_side_effect
    return db


def test_add_chunk_inserts_to_supabase():
    """add_chunk should insert a row scoped by user_id and return its id."""
    emb = [1.0] + [0.0] * 767
    db = _fake_db(insert_id=42)

    with patch("app.memory.index.get_db", return_value=db):
        rowid = add_chunk("user-1", "conv-A", "Pineapples are tropical.", emb)

    assert rowid == 42
    db.table.assert_called_with("memory_chunks")
    inserted = db.table.return_value.insert.call_args[0][0]
    assert inserted["user_id"] == "user-1"
    assert inserted["conv_id"] == "conv-A"
    assert inserted["text"] == "Pineapples are tropical."
    assert inserted["embedding"] == emb


def test_add_chunk_returns_none_on_failure():
    """If Supabase raises, add_chunk degrades gracefully to None."""
    db = MagicMock()
    db.table.return_value.insert.return_value.execute.side_effect = Exception("down")
    with patch("app.memory.index.get_db", return_value=db):
        assert add_chunk("user-1", "conv-A", "text", [0.0] * 768) is None


def test_retrieve_fuses_vector_and_fts():
    """retrieve should pass the right RPC params and fuse both result lists."""
    emb = [1.0] + [0.0] * 767
    vec_rows = [{"id": 1, "conv_id": "conv-A", "text": "Pineapples are tropical."}]
    fts_rows = [{"id": 2, "conv_id": "conv-B", "text": "Database vector search."}]
    db = _fake_db(vec_rows=vec_rows, fts_rows=fts_rows)

    async def mock_embed(text, *args, **kwargs):
        return emb

    with patch("app.memory.retrieve.get_db", return_value=db):
        with patch("app.memory.retrieve.embed", side_effect=mock_embed):
            hits = asyncio.run(
                retrieve("something tropical", user_id="user-1", active_conv_id="conv-X")
            )

    texts = {h["text"] for h in hits}
    assert "Pineapples are tropical." in texts
    assert "Database vector search." in texts

    # Vector RPC received the embedding + user scope + active-conv exclusion
    vec_call = next(c for c in db.rpc.call_args_list if c[0][0] == "match_memory_chunks")
    params = vec_call[0][1]
    assert params["query_embedding"] == emb
    assert params["match_user_id"] == "user-1"
    assert params["exclude_conv_id"] == "conv-X"


def test_retrieve_falls_back_to_fts_when_embedding_fails():
    """If embedding generation fails, retrieve must still run FTS-only."""
    fts_rows = [{"id": 5, "conv_id": "conv-A", "text": "UniqueKeywordHere token."}]
    db = _fake_db(vec_rows=[], fts_rows=fts_rows)

    async def mock_embed_fail(text, *args, **kwargs):
        raise Exception("API key expired")

    with patch("app.memory.retrieve.get_db", return_value=db):
        with patch("app.memory.retrieve.embed", side_effect=mock_embed_fail):
            hits = asyncio.run(retrieve("UniqueKeywordHere", user_id="user-1"))

    assert len(hits) == 1
    assert "UniqueKeywordHere" in hits[0]["text"]
    # Vector RPC must be skipped entirely when there is no embedding
    assert all(c[0][0] != "match_memory_chunks" for c in db.rpc.call_args_list)


def test_retrieve_returns_empty_when_supabase_unavailable():
    """If Supabase is unreachable, retrieve degrades to an empty list."""
    async def mock_embed(text, *args, **kwargs):
        return [0.0] * 768

    with patch("app.memory.retrieve.get_db", side_effect=Exception("no supabase")):
        with patch("app.memory.retrieve.embed", side_effect=mock_embed):
            hits = asyncio.run(retrieve("anything", user_id="user-1"))
    assert hits == []


def test_chat_yields_memory_hit_events(client):
    """If retrieve() returns hits, /chat must stream memory_hit SSE events."""
    storage.create_conversation(user_id="test-user-id", conv_id="active-conv")

    emb = [1.0] + [0.0] * 767
    vec_rows = [{"id": 1, "conv_id": "past-conv", "text": "Remember that Bob loves blue cheese."}]
    db = _fake_db(vec_rows=vec_rows, fts_rows=[])

    async def mock_embed(text, *args, **kwargs):
        return emb

    async def mock_stream(*args, **kwargs):
        yield "Response"

    with patch("app.memory.retrieve.get_db", return_value=db):
        with patch("app.memory.retrieve.embed", side_effect=mock_embed):
            with patch("app.core.normalize.stream_llm", side_effect=mock_stream):
                with client.stream(
                    "POST",
                    "/chat",
                    json={
                        "messages": [{"role": "user", "content": "What cheese does Bob like?"}],
                        "conversation_id": "active-conv",
                    },
                ) as resp:
                    body = resp.read().decode()

    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:].strip()))

    memory_hits = [e for e in events if e.get("type") == "memory_hit"]
    assert len(memory_hits) == 1
    assert "Bob loves blue cheese" in memory_hits[0]["summary"]
