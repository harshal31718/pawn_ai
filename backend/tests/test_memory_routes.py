"""Tests for routes/memory.py — scoped rebuild/clear (Phase M — memory
scoping, M.6). Drive is faked via FakeDriveStorage; Postgres + embed calls
are mocked (no real DB, no real API calls), per testing.md.
"""

from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.storage import conversations_drive as storage
from app.storage import projects_drive
from tests.fake_drive import FakeDriveStorage

TEST_USER_ID = "test-user-id"


@pytest.fixture()
def fake_drive():
    return FakeDriveStorage()


@pytest.fixture()
def client(fake_drive):
    with patch("app.core.drive_factory.get_drive_for_user", return_value=fake_drive):
        with TestClient(app) as c:
            yield c


@pytest.fixture(autouse=True)
def fake_pg_execute():
    # routes/memory.py binds `execute` at module-import time (mirroring
    # routes/projects.py), while memory/indexer.py's rebuild_index re-imports
    # it locally on every call -- patch the underlying postgres_client
    # function AND the already-bound route-module name with the same mock so
    # both call sites (and this fixture's assertions) see one recording.
    with patch("app.db.postgres_client.execute") as mock_execute:
        with patch("app.routes.memory.execute", mock_execute):
            yield mock_execute


def test_rebuild_missing_chat_404(client):
    resp = client.post("/memory/rebuild", json={"scope_type": "chat", "scope_id": "nope"})
    assert resp.status_code == 404


def test_rebuild_missing_project_404(client):
    resp = client.post("/memory/rebuild", json={"scope_type": "project", "scope_id": "nope"})
    assert resp.status_code == 404


def test_rebuild_invalid_scope_type_400(client, fake_drive):
    meta = storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="Chat")
    resp = client.post("/memory/rebuild", json={"scope_type": "bogus", "scope_id": meta["id"]})
    assert resp.status_code == 400


def test_rebuild_chat_scope_reindexes_from_drive(client, fake_drive, fake_pg_execute):
    meta = storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="Chat")
    conv_id = meta["id"]
    storage.append_rag_chunks(
        fake_drive,
        conv_id,
        [{"chunk_id": "c1", "conv_id": conv_id, "msg_index": 0, "text": "hello world"}],
    )

    with patch("app.memory.embed.embed", new=AsyncMock(return_value=[0.1] * 768)):
        with patch("app.memory.index.add_chunk") as fake_add_chunk:
            resp = client.post("/memory/rebuild", json={"scope_type": "chat", "scope_id": conv_id})

    assert resp.status_code == 200
    assert resp.json()["chunks_indexed"] == 1
    fake_add_chunk.assert_called_once()

    delete_calls = [c for c in fake_pg_execute.call_args_list if "delete from memory_chunks" in c[0][0]]
    assert len(delete_calls) == 1
    sql, params = delete_calls[0][0]
    assert "scope_type = %s" in sql
    assert params == (TEST_USER_ID, "chat", conv_id)


def test_clear_missing_scope_404(client):
    resp = client.post("/memory/clear", json={"scope_type": "chat", "scope_id": "nope"})
    assert resp.status_code == 404


def test_clear_chat_scope_wipes_drive_and_postgres(client, fake_drive, fake_pg_execute):
    meta = storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="Chat")
    conv_id = meta["id"]
    storage.append_rag_chunks(
        fake_drive,
        conv_id,
        [{"chunk_id": "c1", "conv_id": conv_id, "msg_index": 0, "text": "secret"}],
    )
    assert storage.load_rag_chunks(fake_drive, conv_id) != []

    resp = client.post("/memory/clear", json={"scope_type": "chat", "scope_id": conv_id})
    assert resp.status_code == 200

    assert storage.load_rag_chunks(fake_drive, conv_id) == []
    delete_calls = [c for c in fake_pg_execute.call_args_list if "delete from memory_chunks" in c[0][0]]
    assert len(delete_calls) == 1
    sql, params = delete_calls[0][0]
    assert params == (TEST_USER_ID, "chat", conv_id)


def test_clear_project_scope_wipes_every_contained_chat(client, fake_drive, fake_pg_execute):
    resp = client.post("/projects", json={"name": "Proj"})
    project_id = resp.json()["id"]
    meta = storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="Chat")
    conv_id = meta["id"]
    project_folder = projects_drive._project_folder(fake_drive, project_id)
    chats_folder = storage._chats_folder(fake_drive)
    projects_drive.move_chat(fake_drive, conv_id, chats_folder, project_folder)
    storage.append_rag_chunks(
        fake_drive,
        conv_id,
        [{"chunk_id": "c1", "conv_id": conv_id, "msg_index": 0, "text": "shared secret"}],
    )

    resp = client.post("/memory/clear", json={"scope_type": "project", "scope_id": project_id})
    assert resp.status_code == 200

    assert storage.load_rag_chunks(fake_drive, conv_id) == []
    delete_calls = [c for c in fake_pg_execute.call_args_list if "delete from memory_chunks" in c[0][0]]
    sql, params = delete_calls[0][0]
    assert params == (TEST_USER_ID, "project", project_id)
