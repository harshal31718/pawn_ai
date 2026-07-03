"""Tests for the Postgres-backed memory layer (index + retrieve).

The Postgres client functions (fetchone/fetchall) are mocked — these tests
verify the Python-side orchestration: correct SQL-function parameters, RRF
fusion, FTS fallback when embedding fails, and the memory_hit SSE event
emission. They do not require a live Postgres instance.
"""

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.storage import conversations_drive as storage
from app.memory.index import add_chunk
from app.memory.retrieve import retrieve
from tests.fake_drive import FakeDriveStorage


@pytest.fixture()
def fake_drive():
    return FakeDriveStorage()


@pytest.fixture()
def client(fake_drive):
    with patch("app.core.drive_factory.get_drive_for_user", return_value=fake_drive):
        with TestClient(app) as c:
            yield c


def _fake_fetchall(vec_rows=None, fts_rows=None):
    """Route to vec_rows/fts_rows based on which SQL function is being called."""
    def _fetchall(sql, params=()):
        if "match_memory_chunks" in sql:
            return vec_rows or []
        if "search_memory_chunks" in sql:
            return fts_rows or []
        return []
    return _fetchall


def test_add_chunk_inserts_to_postgres():
    """add_chunk should insert a row scoped by user_id and return its id."""
    emb = [1.0] + [0.0] * 767
    fake_fetchone = MagicMock(return_value={"id": 42})

    with patch("app.memory.index.fetchone", fake_fetchone):
        rowid = add_chunk("user-1", "conv-A", "Pineapples are tropical.", emb)

    assert rowid == 42
    sql, params = fake_fetchone.call_args[0]
    assert "insert into memory_chunks" in sql
    assert params == ("user-1", "conv-A", "Pineapples are tropical.", emb)


def test_add_chunk_returns_none_on_failure():
    """If Postgres raises, add_chunk degrades gracefully to None."""
    with patch("app.memory.index.fetchone", side_effect=Exception("down")):
        assert add_chunk("user-1", "conv-A", "text", [0.0] * 768) is None


def test_retrieve_fuses_vector_and_fts():
    """retrieve should pass the right SQL-function params and fuse both result lists."""
    emb = [1.0] + [0.0] * 767
    vec_rows = [{"id": 1, "conv_id": "conv-A", "text": "Pineapples are tropical."}]
    fts_rows = [{"id": 2, "conv_id": "conv-B", "text": "Database vector search."}]
    fake_fetchall = MagicMock(side_effect=_fake_fetchall(vec_rows, fts_rows))

    async def mock_embed(text, *args, **kwargs):
        return emb

    with patch("app.memory.retrieve.fetchall", fake_fetchall):
        with patch("app.memory.retrieve.embed", side_effect=mock_embed):
            hits = asyncio.run(
                retrieve("something tropical", user_id="user-1", active_conv_id="conv-X")
            )

    texts = {h["text"] for h in hits}
    assert "Pineapples are tropical." in texts
    assert "Database vector search." in texts

    # Vector call received the embedding + user scope + active-conv exclusion
    vec_call = next(c for c in fake_fetchall.call_args_list if "match_memory_chunks" in c[0][0])
    params = vec_call[0][1]
    assert params[0] == emb
    assert params[1] == "user-1"
    assert params[2] == "conv-X"


def test_retrieve_falls_back_to_fts_when_embedding_fails():
    """If embedding generation fails, retrieve must still run FTS-only."""
    fts_rows = [{"id": 5, "conv_id": "conv-A", "text": "UniqueKeywordHere token."}]
    fake_fetchall = MagicMock(side_effect=_fake_fetchall([], fts_rows))

    async def mock_embed_fail(text, *args, **kwargs):
        raise Exception("API key expired")

    with patch("app.memory.retrieve.fetchall", fake_fetchall):
        with patch("app.memory.retrieve.embed", side_effect=mock_embed_fail):
            hits = asyncio.run(retrieve("UniqueKeywordHere", user_id="user-1"))

    assert len(hits) == 1
    assert "UniqueKeywordHere" in hits[0]["text"]
    # Vector search must be skipped entirely when there is no embedding
    assert all("match_memory_chunks" not in c[0][0] for c in fake_fetchall.call_args_list)


def test_retrieve_returns_empty_when_postgres_unavailable():
    """If Postgres is unreachable, retrieve degrades to an empty list."""
    async def mock_embed(text, *args, **kwargs):
        return [0.0] * 768

    with patch("app.memory.retrieve.fetchall", side_effect=Exception("no postgres")):
        with patch("app.memory.retrieve.embed", side_effect=mock_embed):
            hits = asyncio.run(retrieve("anything", user_id="user-1"))
    assert hits == []


def test_chat_yields_memory_hit_events(client, fake_drive):
    """If retrieve() returns hits, /chat must stream memory_hit SSE events."""
    storage.create_conversation(fake_drive, user_id="test-user-id", conv_id="active-conv")

    emb = [1.0] + [0.0] * 767
    vec_rows = [{"id": 1, "conv_id": "past-conv", "text": "Remember that Bob loves blue cheese."}]
    fake_fetchall = MagicMock(side_effect=_fake_fetchall(vec_rows, []))

    async def mock_embed(text, *args, **kwargs):
        return emb

    async def mock_stream(*args, **kwargs):
        yield "Response"

    with patch("app.memory.retrieve.fetchall", fake_fetchall):
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
