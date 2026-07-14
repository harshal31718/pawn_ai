"""Tests for the Postgres-backed memory layer (index + retrieve).

The Postgres client functions (fetchone/fetchall) are mocked — these tests
verify the Python-side orchestration: correct SQL-function parameters, RRF
fusion, FTS fallback when embedding fails, and the memory_hit SSE event
emission. They do not require a live Postgres instance.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

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
        if "match_scoped_chunks" in sql:
            return vec_rows or []
        if "search_scoped_chunks" in sql:
            return fts_rows or []
        return []
    return _fetchall


def _fake_scoped_fetchall(chunks):
    """Simulates match_scoped_chunks/search_scoped_chunks's strict
    user_id+scope_type+scope_id WHERE filtering entirely in Python, keyed off
    the params retrieve() actually passes -- proves the Python call contract
    enforces scope isolation, not just that the (mocked) SQL layer would."""
    def _fetchall(sql, params=()):
        if "match_scoped_chunks" in sql:
            _emb, user_id, scope_type, scope_id, _kind, _limit = params
        elif "search_scoped_chunks" in sql:
            _query, user_id, scope_type, scope_id, _kind, _limit = params
        else:
            return []
        return [
            {"id": c["id"], "conv_id": c["conv_id"], "text": c["text"]}
            for c in chunks
            if c["user_id"] == user_id
            and c["scope_type"] == scope_type
            and c["scope_id"] == scope_id
        ]
    return _fetchall


def test_add_chunk_inserts_to_postgres():
    """add_chunk should insert a row scoped by (user_id, scope_type, scope_id) and return its id."""
    emb = [1.0] + [0.0] * 767
    fake_fetchone = MagicMock(return_value={"id": 42})

    with patch("app.memory.index.fetchone", fake_fetchone):
        rowid = add_chunk(
            "user-1", "chat", "conv-A", "conv-A", "chunk-1", 0, "Pineapples are tropical.", emb
        )

    assert rowid == 42
    sql, params = fake_fetchone.call_args[0]
    assert "insert into memory_chunks" in sql
    # kind defaults to 'message', doc_id to None, when not passed (Phase A / A.4).
    assert params == ("user-1", "chat", "conv-A", "conv-A", "chunk-1", 0, "Pineapples are tropical.", emb, "message", None)


def test_add_chunk_returns_none_on_failure():
    """If Postgres raises, add_chunk degrades gracefully to None."""
    with patch("app.memory.index.fetchone", side_effect=Exception("down")):
        assert add_chunk("user-1", "chat", "conv-A", "conv-A", "chunk-1", 0, "text", [0.0] * 768) is None


def test_add_chunk_upserts_idempotently_on_chunk_id():
    """Re-indexing the same chunk_id must issue an ON CONFLICT upsert, not a plain insert."""
    emb = [1.0] + [0.0] * 767
    fake_fetchone = MagicMock(return_value={"id": 42})

    with patch("app.memory.index.fetchone", fake_fetchone):
        first = add_chunk("user-1", "chat", "conv-A", "conv-A", "chunk-1", 0, "text v1", emb)
        second = add_chunk("user-1", "chat", "conv-A", "conv-A", "chunk-1", 0, "text v2", emb)

    assert first == second == 42
    for call in fake_fetchone.call_args_list:
        sql = call[0][0]
        assert "on conflict (user_id, chunk_id)" in sql
        assert "do update set" in sql


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
                retrieve(
                    "something tropical", user_id="user-1", scope_type="chat", scope_id="conv-X",
                    match_kind="message",
                )
            )

    texts = {h["text"] for h in hits}
    assert "Pineapples are tropical." in texts
    assert "Database vector search." in texts

    # Vector call received the embedding + user + strict scope equality + kind filter
    vec_call = next(c for c in fake_fetchall.call_args_list if "match_scoped_chunks" in c[0][0])
    params = vec_call[0][1]
    assert params[0] == emb
    assert params[1] == "user-1"
    assert params[2] == "chat"
    assert params[3] == "conv-X"
    assert params[4] == "message"


def test_retrieve_falls_back_to_fts_when_embedding_fails():
    """If embedding generation fails, retrieve must still run FTS-only."""
    fts_rows = [{"id": 5, "conv_id": "conv-A", "text": "UniqueKeywordHere token."}]
    fake_fetchall = MagicMock(side_effect=_fake_fetchall([], fts_rows))

    async def mock_embed_fail(text, *args, **kwargs):
        raise Exception("API key expired")

    with patch("app.memory.retrieve.fetchall", fake_fetchall):
        with patch("app.memory.retrieve.embed", side_effect=mock_embed_fail):
            hits = asyncio.run(retrieve("UniqueKeywordHere", user_id="user-1", scope_type="chat", scope_id="conv-A"))

    assert len(hits) == 1
    assert "UniqueKeywordHere" in hits[0]["text"]
    # Vector search must be skipped entirely when there is no embedding
    assert all("match_scoped_chunks" not in c[0][0] for c in fake_fetchall.call_args_list)


def test_retrieve_returns_empty_when_postgres_unavailable():
    """If Postgres is unreachable, retrieve degrades to an empty list."""
    async def mock_embed(text, *args, **kwargs):
        return [0.0] * 768

    with patch("app.memory.retrieve.fetchall", side_effect=Exception("no postgres")):
        with patch("app.memory.retrieve.embed", side_effect=mock_embed):
            hits = asyncio.run(retrieve("anything", user_id="user-1", scope_type="chat", scope_id="conv-A"))
    assert hits == []


def test_retrieve_cross_scope_miss_isolation_guarantee():
    """Core isolation guarantee of Phase M: a topic indexed under one chat's
    scope must NEVER surface when a different chat (different scope_id)
    queries its own scope, even for the same user and the same query text."""
    emb = [1.0] + [0.0] * 767
    chunks = [
        {
            "id": 1,
            "user_id": "user-1",
            "scope_type": "chat",
            "scope_id": "chat-A",
            "conv_id": "chat-A",
            "text": "Project Nightingale launches in Q3.",
        },
    ]
    fake_fetchall = MagicMock(side_effect=_fake_scoped_fetchall(chunks))

    async def mock_embed(text, *args, **kwargs):
        return emb

    with patch("app.memory.retrieve.fetchall", fake_fetchall):
        with patch("app.memory.retrieve.embed", side_effect=mock_embed):
            hits_a = asyncio.run(
                retrieve("Nightingale", user_id="user-1", scope_type="chat", scope_id="chat-A")
            )
            hits_b = asyncio.run(
                retrieve("Nightingale", user_id="user-1", scope_type="chat", scope_id="chat-B")
            )

    assert len(hits_a) == 1
    assert "Nightingale" in hits_a[0]["text"]
    assert hits_b == []


def test_retrieve_cross_scope_document_isolation_guarantee():
    """Phase A / A.4: a document chunk (kind='document') indexed under one
    chat's scope must never surface via doc_search (match_kind='document')
    when a different chat scope queries it — the same isolation guarantee
    Phase M proved for message chunks, now exercised for documents."""
    emb = [1.0] + [0.0] * 767
    chunks = [
        {
            "id": 1,
            "user_id": "user-1",
            "scope_type": "chat",
            "scope_id": "chat-A",
            "conv_id": "chat-A",
            "text": "Quarterly revenue figures from the uploaded PDF.",
        },
    ]
    fake_fetchall = MagicMock(side_effect=_fake_scoped_fetchall(chunks))

    async def mock_embed(text, *args, **kwargs):
        return emb

    with patch("app.memory.retrieve.fetchall", fake_fetchall):
        with patch("app.memory.retrieve.embed", side_effect=mock_embed):
            hits_a = asyncio.run(
                retrieve(
                    "revenue", user_id="user-1", scope_type="chat", scope_id="chat-A",
                    match_kind="document",
                )
            )
            hits_b = asyncio.run(
                retrieve(
                    "revenue", user_id="user-1", scope_type="chat", scope_id="chat-B",
                    match_kind="document",
                )
            )

    assert len(hits_a) == 1
    assert "revenue" in hits_a[0]["text"].lower()
    assert hits_b == []  # different chat scope — the document is invisible


def test_retrieve_project_scope_shared_across_member_chats():
    """A project-scoped chunk (written by one member chat) must be
    retrievable when querying the project's own scope."""
    emb = [1.0] + [0.0] * 767
    chunks = [
        {
            "id": 1,
            "user_id": "user-1",
            "scope_type": "project",
            "scope_id": "proj-1",
            "conv_id": "chat-A",
            "text": "Shared project decision: use Postgres.",
        },
    ]
    fake_fetchall = MagicMock(side_effect=_fake_scoped_fetchall(chunks))

    async def mock_embed(text, *args, **kwargs):
        return emb

    with patch("app.memory.retrieve.fetchall", fake_fetchall):
        with patch("app.memory.retrieve.embed", side_effect=mock_embed):
            hits = asyncio.run(
                retrieve("shared decision", user_id="user-1", scope_type="project", scope_id="proj-1")
            )
            miss = asyncio.run(
                retrieve("shared decision", user_id="user-1", scope_type="chat", scope_id="chat-A")
            )

    assert len(hits) == 1
    assert hits[0]["conv_id"] == "chat-A"
    # The chunk's provenance chat, queried standalone (its own 'chat' scope,
    # not the project it's currently in), must NOT see the project chunk.
    assert miss == []


def test_chat_yields_memory_hit_events(client, fake_drive):
    """If the agent calls the search_memory tool and retrieve() returns hits,
    /chat must stream memory_hit SSE events carrying scope + source_conv_id
    (Phase A / A.6: native tool calling replaces the old ReAct JSON protocol
    -- force needs_agent=True since the test message is otherwise 'light' and
    would take the direct_answer fast path with no tools at all)."""
    storage.create_conversation(fake_drive, user_id="test-user-id", conv_id="active-conv")

    emb = [1.0] + [0.0] * 767
    vec_rows = [{"id": 1, "conv_id": "past-conv", "text": "Remember that Bob loves blue cheese."}]
    fake_fetchall = MagicMock(side_effect=_fake_fetchall(vec_rows, []))

    async def mock_embed(text, *args, **kwargs):
        return emb

    async def mock_complete(model_id, messages, resolver, rate_limiter, user_id=None, tools=None, tool_choice="auto", **kwargs):
        assert tool_choice == "none"  # plan step -- the only chat_complete caller left
        return {"role": "assistant", "content": "1. search memory", "usage": {}}

    exec_calls = {"n": 0}

    async def mock_stream_with_tools(*args, **kwargs):
        exec_calls["n"] += 1
        if exec_calls["n"] == 1:
            yield {
                "type": "done",
                "tool_calls": [{
                    "id": "call_1", "type": "function",
                    "function": {"name": "search_memory", "arguments": '{"query": "What cheese does Bob like?"}'},
                }],
                "finish_reason": "tool_calls",
                "usage": {},
            }
        else:
            yield {"type": "content", "delta": "Response"}
            yield {"type": "done", "tool_calls": None, "finish_reason": "stop", "usage": {}}

    with patch("app.agent.graph.router_classify", new=AsyncMock(return_value={"difficulty": "heavy", "needs_agent": True})):
        with patch("app.memory.retrieve.fetchall", fake_fetchall):
            with patch("app.memory.retrieve.embed", side_effect=mock_embed):
                with patch("app.core.normalize.chat_complete", side_effect=mock_complete):
                    with patch("app.core.normalize.chat_stream_with_tools", side_effect=mock_stream_with_tools):
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
    assert memory_hits[0]["scope"] == "chat"
    assert memory_hits[0]["source_conv_id"] == "past-conv"


def test_stateless_chat_never_queries_memory(client):
    """Phase M, M.4: a stateless request (no conversation_id) resolves no
    scope, so search_memory isn't even in the toolset (registry.py gates it
    on ctx.scope_type is not None) -- retrieve() must never be called and no
    memory_hit event can fire, regardless of what the model tries to call."""

    async def mock_complete(model_id, messages, resolver, rate_limiter, user_id=None, tools=None, tool_choice="auto", **kwargs):
        assert tool_choice == "none"  # plan step -- the only chat_complete caller left
        return {"role": "assistant", "content": "1. try to search memory", "usage": {}}

    exec_calls = {"n": 0}

    async def mock_stream_with_tools(*args, **kwargs):
        exec_calls["n"] += 1
        if exec_calls["n"] == 1:
            yield {
                "type": "done",
                "tool_calls": [{
                    "id": "call_1", "type": "function",
                    "function": {"name": "search_memory", "arguments": '{"query": "anything"}'},
                }],
                "finish_reason": "tool_calls",
                "usage": {},
            }
        else:
            yield {"type": "content", "delta": "Response"}
            yield {"type": "done", "tool_calls": None, "finish_reason": "stop", "usage": {}}

    fake_retrieve = MagicMock()
    with patch("app.agent.graph.router_classify", new=AsyncMock(return_value={"difficulty": "heavy", "needs_agent": True})):
        with patch("app.memory.retrieve.retrieve", fake_retrieve):
            with patch("app.core.normalize.chat_complete", side_effect=mock_complete):
                with patch("app.core.normalize.chat_stream_with_tools", side_effect=mock_stream_with_tools):
                    with client.stream(
                        "POST",
                        "/chat",
                        json={"messages": [{"role": "user", "content": "hello"}]},
                    ) as resp:
                        body = resp.read().decode()

    fake_retrieve.assert_not_called()
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:].strip()))
    assert not [e for e in events if e.get("type") == "memory_hit"]
