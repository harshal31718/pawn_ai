"""Tests for memory/indexer.py (Phase M, M.3) — scope resolution and the
chunk/write path. FakeDriveStorage stands in for Drive; embed() and
Postgres's add_chunk/execute are mocked — no real API/DB calls."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.memory import indexer
from app.storage import conversations_drive, projects_drive
from tests.fake_drive import FakeDriveStorage


@pytest.fixture(autouse=True)
def _clear_scope_cache():
    """resolve_scope caches in-process; keep tests isolated from each other."""
    indexer._SCOPE_CACHE.clear()
    yield
    indexer._SCOPE_CACHE.clear()


@pytest.fixture()
def fake_drive():
    return FakeDriveStorage()


async def _mock_embed(text, *args, **kwargs):
    return [0.1] * 768


# ─── resolve_scope ───────────────────────────────────────────────────────────


def test_resolve_scope_standalone_chat(fake_drive):
    conversations_drive.create_conversation(fake_drive, user_id="u1", conv_id="conv-1")
    scope = indexer.resolve_scope("u1", "conv-1", drive=fake_drive)
    assert scope == ("chat", "conv-1")


def test_resolve_scope_project_chat(fake_drive):
    conversations_drive.create_conversation(fake_drive, user_id="u1", conv_id="conv-1")
    projects_drive.create_project(fake_drive, project_id="proj-1", name="Proj")
    chats_folder = conversations_drive._chats_folder(fake_drive)
    project_folder = projects_drive._project_folder(fake_drive, "proj-1")
    projects_drive.move_chat(fake_drive, "conv-1", chats_folder, project_folder)

    scope = indexer.resolve_scope("u1", "conv-1", drive=fake_drive)
    assert scope == ("project", "proj-1")


def test_resolve_scope_missing_chat_returns_none(fake_drive):
    assert indexer.resolve_scope("u1", "does-not-exist", drive=fake_drive) is None


def test_resolve_scope_is_cached(fake_drive):
    conversations_drive.create_conversation(fake_drive, user_id="u1", conv_id="conv-1")
    first = indexer.resolve_scope("u1", "conv-1", drive=fake_drive)

    # Even if the chat vanishes from Drive, a cached result should still be
    # served within the TTL window (no re-walk).
    with patch.object(conversations_drive, "resolve_conv_scope", return_value=None) as mock_walk:
        second = indexer.resolve_scope("u1", "conv-1", drive=fake_drive)
    assert second == first == ("chat", "conv-1")
    mock_walk.assert_not_called()


def test_evict_scope_forces_re_resolution(fake_drive):
    conversations_drive.create_conversation(fake_drive, user_id="u1", conv_id="conv-1")
    indexer.resolve_scope("u1", "conv-1", drive=fake_drive)
    indexer.evict_scope("u1", "conv-1")

    with patch.object(
        conversations_drive, "resolve_conv_scope", return_value=("project", "proj-9")
    ) as mock_walk:
        scope = indexer.resolve_scope("u1", "conv-1", drive=fake_drive)
    assert scope == ("project", "proj-9")
    mock_walk.assert_called_once()


# ─── index_turn_task ─────────────────────────────────────────────────────────


def test_index_turn_task_writes_drive_then_postgres(fake_drive):
    conversations_drive.create_conversation(fake_drive, user_id="u1", conv_id="conv-1")
    conversations_drive.append_messages(
        fake_drive,
        "conv-1",
        [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
    )
    turn = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]

    fake_add_chunk = MagicMock(return_value=1)
    with patch("app.core.drive_factory.get_drive_for_user", return_value=fake_drive):
        with patch("app.memory.embed.embed", side_effect=_mock_embed):
            with patch("app.memory.index.add_chunk", fake_add_chunk):
                asyncio.run(indexer.index_turn_task("u1", "conv-1", None, turn))

    drive_chunks = conversations_drive.load_rag_chunks(fake_drive, "conv-1")
    assert len(drive_chunks) == 2
    assert all(c["conv_id"] == "conv-1" for c in drive_chunks)

    assert fake_add_chunk.call_count == 2
    for call in fake_add_chunk.call_args_list:
        user_id, scope_type, scope_id, conv_id = call[0][0], call[0][1], call[0][2], call[0][3]
        assert (user_id, scope_type, scope_id, conv_id) == ("u1", "chat", "conv-1", "conv-1")


def test_index_turn_task_project_scope(fake_drive):
    conversations_drive.create_conversation(fake_drive, user_id="u1", conv_id="conv-1")
    projects_drive.create_project(fake_drive, project_id="proj-1", name="Proj")
    chats_folder = conversations_drive._chats_folder(fake_drive)
    project_folder = projects_drive._project_folder(fake_drive, "proj-1")
    projects_drive.move_chat(fake_drive, "conv-1", chats_folder, project_folder)

    turn = [{"role": "user", "content": "in a project"}]
    fake_add_chunk = MagicMock(return_value=1)
    with patch("app.core.drive_factory.get_drive_for_user", return_value=fake_drive):
        with patch("app.memory.embed.embed", side_effect=_mock_embed):
            with patch("app.memory.index.add_chunk", fake_add_chunk):
                asyncio.run(indexer.index_turn_task("u1", "conv-1", None, turn))

    call = fake_add_chunk.call_args_list[0]
    assert (call[0][1], call[0][2]) == ("project", "proj-1")


def test_index_turn_task_stateless_chat_never_indexed(fake_drive):
    fake_add_chunk = MagicMock()
    with patch("app.core.drive_factory.get_drive_for_user", return_value=fake_drive):
        with patch("app.memory.index.add_chunk", fake_add_chunk):
            asyncio.run(indexer.index_turn_task("u1", None, None, [{"role": "user", "content": "hi"}]))
    fake_add_chunk.assert_not_called()


def test_index_turn_task_drive_unavailable_writes_nothing(fake_drive):
    fake_add_chunk = MagicMock()
    with patch("app.core.drive_factory.get_drive_for_user", return_value=None):
        with patch("app.memory.index.add_chunk", fake_add_chunk):
            asyncio.run(
                indexer.index_turn_task(
                    "u1", "conv-1", None, [{"role": "user", "content": "hi"}]
                )
            )
    fake_add_chunk.assert_not_called()


def test_index_turn_task_drive_write_failure_skips_postgres(fake_drive):
    """If the Drive-side chunk write fails mid-operation, no Postgres rows
    must be written — Drive failure aborts before Postgres (no orphan index)."""
    conversations_drive.create_conversation(fake_drive, user_id="u1", conv_id="conv-1")
    turn = [{"role": "user", "content": "hi"}]

    fake_add_chunk = MagicMock()
    with patch("app.core.drive_factory.get_drive_for_user", return_value=fake_drive):
        with patch.object(
            conversations_drive, "append_rag_chunks", side_effect=Exception("drive down")
        ):
            with patch("app.memory.index.add_chunk", fake_add_chunk):
                asyncio.run(indexer.index_turn_task("u1", "conv-1", None, turn))

    fake_add_chunk.assert_not_called()


def test_index_turn_task_embed_failure_skips_that_chunk_only(fake_drive):
    """A single chunk's embed failure must not block the Drive-side write
    (already committed) nor other chunks' Postgres writes."""
    conversations_drive.create_conversation(fake_drive, user_id="u1", conv_id="conv-1")
    turn = [{"role": "user", "content": "ok"}, {"role": "assistant", "content": "also ok"}]

    call_count = {"n": 0}

    async def flaky_embed(text, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise Exception("embed API down")
        return [0.1] * 768

    fake_add_chunk = MagicMock(return_value=1)
    with patch("app.core.drive_factory.get_drive_for_user", return_value=fake_drive):
        with patch("app.memory.embed.embed", side_effect=flaky_embed):
            with patch("app.memory.index.add_chunk", fake_add_chunk):
                asyncio.run(indexer.index_turn_task("u1", "conv-1", None, turn))

    # Drive still has both chunks (written before embedding starts).
    assert len(conversations_drive.load_rag_chunks(fake_drive, "conv-1")) == 2
    # Only the chunk whose embed succeeded reached Postgres.
    assert fake_add_chunk.call_count == 1


# ─── rebuild_index ───────────────────────────────────────────────────────────


def test_rebuild_index_deletes_then_reinserts_from_drive(fake_drive):
    conversations_drive.create_conversation(fake_drive, user_id="u1", conv_id="conv-1")
    conversations_drive.append_rag_chunks(
        fake_drive,
        "conv-1",
        [
            {"chunk_id": "c1", "conv_id": "conv-1", "msg_index": 0, "text": "alpha", "created_at": "t"},
            {"chunk_id": "c2", "conv_id": "conv-1", "msg_index": 1, "text": "beta", "created_at": "t"},
        ],
    )

    fake_execute = MagicMock()
    fake_add_chunk = MagicMock(return_value=1)
    with patch("app.core.drive_factory.get_drive_for_user", return_value=fake_drive):
        with patch("app.db.postgres_client.execute", fake_execute):
            with patch("app.memory.embed.embed", side_effect=_mock_embed):
                with patch("app.memory.index.add_chunk", fake_add_chunk):
                    total = asyncio.run(indexer.rebuild_index("u1", "chat", "conv-1"))

    assert total == 2
    fake_execute.assert_called_once()
    delete_sql, delete_params = fake_execute.call_args[0]
    assert "delete from memory_chunks" in delete_sql
    assert delete_params == ("u1", "chat", "conv-1")
    assert fake_add_chunk.call_count == 2


# ─── index_document_task (Phase A / A.4) ─────────────────────────────────────


def test_index_document_task_writes_postgres_only_not_rag_chunks(fake_drive):
    """Document chunks go straight to Postgres (kind='document') -- unlike
    message turns, they are NOT appended to rag_chunks.jsonl; PAWN/uploads/
    is itself the rebuild source of truth for documents."""
    conversations_drive.create_conversation(fake_drive, user_id="u1", conv_id="conv-1")

    fake_add_chunk = MagicMock(return_value=1)
    with patch("app.core.drive_factory.get_drive_for_user", return_value=fake_drive):
        with patch("app.memory.embed.embed", side_effect=_mock_embed):
            with patch("app.memory.index.add_chunk", fake_add_chunk):
                asyncio.run(
                    indexer.index_document_task(
                        "u1", "conv-1", None, "doc-1", "some document text", "notes.txt"
                    )
                )

    assert conversations_drive.load_rag_chunks(fake_drive, "conv-1") == []
    assert fake_add_chunk.call_count >= 1
    for call in fake_add_chunk.call_args_list:
        assert call.kwargs["kind"] == "document"
        assert call.kwargs["doc_id"] == "doc-1"
        assert call[0][:4] == ("u1", "chat", "conv-1", "conv-1")

    attached = conversations_drive.get_attached_docs(fake_drive, "conv-1")
    assert attached == [{"doc_id": "doc-1", "filename": "notes.txt"}]


def test_index_document_task_project_scope(fake_drive):
    conversations_drive.create_conversation(fake_drive, user_id="u1", conv_id="conv-1")
    projects_drive.create_project(fake_drive, project_id="proj-1", name="Proj")
    chats_folder = conversations_drive._chats_folder(fake_drive)
    project_folder = projects_drive._project_folder(fake_drive, "proj-1")
    projects_drive.move_chat(fake_drive, "conv-1", chats_folder, project_folder)

    fake_add_chunk = MagicMock(return_value=1)
    with patch("app.core.drive_factory.get_drive_for_user", return_value=fake_drive):
        with patch("app.memory.embed.embed", side_effect=_mock_embed):
            with patch("app.memory.index.add_chunk", fake_add_chunk):
                asyncio.run(indexer.index_document_task("u1", "conv-1", None, "doc-1", "text"))

    call = fake_add_chunk.call_args_list[0]
    assert (call[0][1], call[0][2]) == ("project", "proj-1")


def test_index_document_task_stateless_never_indexed(fake_drive):
    fake_add_chunk = MagicMock()
    with patch("app.core.drive_factory.get_drive_for_user", return_value=fake_drive):
        with patch("app.memory.index.add_chunk", fake_add_chunk):
            asyncio.run(indexer.index_document_task("u1", None, None, "doc-1", "text"))
    fake_add_chunk.assert_not_called()


def test_index_document_task_idempotent_attachment(fake_drive):
    """Re-indexing the same doc_id twice doesn't duplicate the attachment
    record (add_attached_doc is a no-op on a repeat doc_id)."""
    conversations_drive.create_conversation(fake_drive, user_id="u1", conv_id="conv-1")
    fake_add_chunk = MagicMock(return_value=1)
    with patch("app.core.drive_factory.get_drive_for_user", return_value=fake_drive):
        with patch("app.memory.embed.embed", side_effect=_mock_embed):
            with patch("app.memory.index.add_chunk", fake_add_chunk):
                asyncio.run(indexer.index_document_task("u1", "conv-1", None, "doc-1", "v1", "a.txt"))
                asyncio.run(indexer.index_document_task("u1", "conv-1", None, "doc-1", "v2", "a.txt"))

    attached = conversations_drive.get_attached_docs(fake_drive, "conv-1")
    assert len(attached) == 1


# ─── rebuild_index: documents (Phase A / A.4) ────────────────────────────────


def test_rebuild_index_re_chunks_attached_documents(fake_drive):
    from app.storage import documents_drive

    conversations_drive.create_conversation(fake_drive, user_id="u1", conv_id="conv-1")
    documents_drive.store_doc("doc-1", "some document body text", fake_drive)
    conversations_drive.add_attached_doc(fake_drive, "conv-1", "doc-1", "report.pdf")

    fake_execute = MagicMock()
    fake_add_chunk = MagicMock(return_value=1)
    with patch("app.core.drive_factory.get_drive_for_user", return_value=fake_drive):
        with patch("app.db.postgres_client.execute", fake_execute):
            with patch("app.memory.embed.embed", side_effect=_mock_embed):
                with patch("app.memory.index.add_chunk", fake_add_chunk):
                    total = asyncio.run(indexer.rebuild_index("u1", "chat", "conv-1"))

    assert total >= 1
    doc_calls = [c for c in fake_add_chunk.call_args_list if c.kwargs.get("kind") == "document"]
    assert len(doc_calls) >= 1
    assert all(c.kwargs["doc_id"] == "doc-1" for c in doc_calls)


def test_rebuild_index_survives_postgres_wipe_via_drive_attachment_record(fake_drive):
    """The whole point of persisting attached_docs on Drive (not just
    Postgres): even if Postgres rows are already gone (manual truncate, or
    just this test never wrote any), rebuild still rediscovers the doc_id
    from meta.json and re-chunks PAWN/uploads/<doc_id>.txt."""
    from app.storage import documents_drive

    conversations_drive.create_conversation(fake_drive, user_id="u1", conv_id="conv-1")
    documents_drive.store_doc("doc-1", "recoverable content", fake_drive)
    conversations_drive.add_attached_doc(fake_drive, "conv-1", "doc-1")
    # No Postgres rows were ever written for this doc_id — simulates a wipe.

    fake_add_chunk = MagicMock(return_value=1)
    with patch("app.core.drive_factory.get_drive_for_user", return_value=fake_drive):
        with patch("app.db.postgres_client.execute", MagicMock()):
            with patch("app.memory.embed.embed", side_effect=_mock_embed):
                with patch("app.memory.index.add_chunk", fake_add_chunk):
                    total = asyncio.run(indexer.rebuild_index("u1", "chat", "conv-1"))

    assert total >= 1
    assert any(c.kwargs.get("doc_id") == "doc-1" for c in fake_add_chunk.call_args_list)


def test_rebuild_index_project_scope_covers_all_member_chats(fake_drive):
    projects_drive.create_project(fake_drive, project_id="proj-1", name="Proj")
    project_folder = projects_drive._project_folder(fake_drive, "proj-1")
    conversations_drive.create_conversation(fake_drive, user_id="u1", conv_id="conv-a")
    conversations_drive.create_conversation(fake_drive, user_id="u1", conv_id="conv-b")
    chats_folder = conversations_drive._chats_folder(fake_drive)
    projects_drive.move_chat(fake_drive, "conv-a", chats_folder, project_folder)
    projects_drive.move_chat(fake_drive, "conv-b", chats_folder, project_folder)
    conversations_drive.append_rag_chunks(
        fake_drive, "conv-a", [{"chunk_id": "c1", "conv_id": "conv-a", "msg_index": 0, "text": "a", "created_at": "t"}]
    )
    conversations_drive.append_rag_chunks(
        fake_drive, "conv-b", [{"chunk_id": "c2", "conv_id": "conv-b", "msg_index": 0, "text": "b", "created_at": "t"}]
    )

    fake_add_chunk = MagicMock(return_value=1)
    with patch("app.core.drive_factory.get_drive_for_user", return_value=fake_drive):
        with patch("app.db.postgres_client.execute", MagicMock()):
            with patch("app.memory.embed.embed", side_effect=_mock_embed):
                with patch("app.memory.index.add_chunk", fake_add_chunk):
                    total = asyncio.run(indexer.rebuild_index("u1", "project", "proj-1"))

    assert total == 2
    scoped_conv_ids = {call[0][3] for call in fake_add_chunk.call_args_list}
    assert scoped_conv_ids == {"conv-a", "conv-b"}
