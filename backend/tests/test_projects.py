"""Tests for routes/projects.py — project CRUD, two-way chat moves, cascade
delete (Phase M — memory scoping, M.5). Drive is faked via FakeDriveStorage;
Postgres calls are mocked (no real DB), per testing.md.
"""

from unittest.mock import MagicMock, patch

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
    """Every route module talks to Postgres via app.db.postgres_client.execute
    -- mock it everywhere it's imported by name (routes/projects.py,
    memory/indexer.py) so no test needs a real database."""
    with patch("app.routes.projects.execute") as mock_execute:
        yield mock_execute


# ─── CRUD ────────────────────────────────────────────────────────────────


def test_project_crud(client):
    resp = client.get("/projects")
    assert resp.status_code == 200
    assert resp.json() == []

    resp = client.post("/projects", json={"name": "Research"})
    assert resp.status_code == 200
    meta = resp.json()
    assert meta["name"] == "Research"
    project_id = meta["id"]

    resp = client.get("/projects")
    assert resp.status_code == 200
    lst = resp.json()
    assert len(lst) == 1
    assert lst[0]["id"] == project_id
    assert lst[0]["chat_count"] == 0

    resp = client.patch(f"/projects/{project_id}", json={"name": "Research v2"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Research v2"

    resp = client.delete(f"/projects/{project_id}")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

    resp = client.get("/projects")
    assert resp.json() == []


def test_create_project_is_idempotent_on_client_id(client):
    resp1 = client.post("/projects", json={"id": "proj-fixed", "name": "First"})
    resp2 = client.post("/projects", json={"id": "proj-fixed", "name": "Second"})
    assert resp1.json() == resp2.json()
    assert resp1.json()["name"] == "First"


def test_rename_missing_project_404(client):
    resp = client.patch("/projects/does-not-exist", json={"name": "x"})
    assert resp.status_code == 404


def test_delete_missing_project_404(client):
    resp = client.delete("/projects/does-not-exist")
    assert resp.status_code == 404


def test_delete_project_cascades_drive_and_postgres(client, fake_drive, fake_pg_execute):
    resp = client.post("/projects", json={"name": "Doomed"})
    project_id = resp.json()["id"]

    meta = storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="Inside")
    conv_id = meta["id"]
    project_folder = projects_drive._project_folder(fake_drive, project_id)
    chats_folder = storage._chats_folder(fake_drive)
    projects_drive.move_chat(fake_drive, conv_id, chats_folder, project_folder)

    resp = client.delete(f"/projects/{project_id}")
    assert resp.status_code == 200

    assert projects_drive.get_project_meta(fake_drive, project_id) is None
    assert storage.get_conversation_meta(fake_drive, conv_id) is None

    delete_calls = [c for c in fake_pg_execute.call_args_list if "delete from memory_chunks" in c[0][0]]
    assert len(delete_calls) == 1
    sql, params = delete_calls[0][0]
    assert "scope_type = 'project'" in sql
    assert params == (TEST_USER_ID, project_id)


# ─── Move in / move out ─────────────────────────────────────────────────


def test_move_chat_in_relocates_drive_and_updates_scope(client, fake_drive, fake_pg_execute):
    resp = client.post("/projects", json={"name": "Proj"})
    project_id = resp.json()["id"]
    meta = storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="Standalone")
    conv_id = meta["id"]

    resp = client.post(f"/projects/{project_id}/chats/{conv_id}")
    assert resp.status_code == 200

    # Drive: chat now lives under the project, not chats/.
    scope = storage.resolve_conv_scope(fake_drive, conv_id)
    assert scope == ("project", project_id)

    # Postgres: scope columns updated for every chunk carrying this conv_id.
    update_calls = [c for c in fake_pg_execute.call_args_list if "update memory_chunks" in c[0][0]]
    assert len(update_calls) == 1
    sql, params = update_calls[0][0]
    assert params == ("project", project_id, TEST_USER_ID, conv_id)


def test_move_chat_in_is_idempotent(client, fake_drive, fake_pg_execute):
    resp = client.post("/projects", json={"name": "Proj"})
    project_id = resp.json()["id"]
    meta = storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="Standalone")
    conv_id = meta["id"]

    r1 = client.post(f"/projects/{project_id}/chats/{conv_id}")
    r2 = client.post(f"/projects/{project_id}/chats/{conv_id}")
    assert r1.status_code == r2.status_code == 200
    assert storage.resolve_conv_scope(fake_drive, conv_id) == ("project", project_id)


def test_move_chat_in_missing_project_404(client, fake_drive):
    meta = storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="Standalone")
    resp = client.post(f"/projects/does-not-exist/chats/{meta['id']}")
    assert resp.status_code == 404


def test_move_chat_in_missing_chat_404(client, fake_drive):
    resp = client.post("/projects", json={"name": "Proj"})
    project_id = resp.json()["id"]
    resp = client.post(f"/projects/{project_id}/chats/does-not-exist")
    assert resp.status_code == 404


def test_move_chat_in_conflicts_with_other_project(client, fake_drive):
    resp = client.post("/projects", json={"name": "A"})
    project_a = resp.json()["id"]
    resp = client.post("/projects", json={"name": "B"})
    project_b = resp.json()["id"]
    meta = storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="Chat")
    conv_id = meta["id"]

    assert client.post(f"/projects/{project_a}/chats/{conv_id}").status_code == 200
    resp = client.post(f"/projects/{project_b}/chats/{conv_id}")
    assert resp.status_code == 409


def test_move_chat_out_relocates_drive_and_updates_scope(client, fake_drive, fake_pg_execute):
    resp = client.post("/projects", json={"name": "Proj"})
    project_id = resp.json()["id"]
    meta = storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="Chat")
    conv_id = meta["id"]
    client.post(f"/projects/{project_id}/chats/{conv_id}")
    fake_pg_execute.reset_mock()

    resp = client.delete(f"/projects/{project_id}/chats/{conv_id}")
    assert resp.status_code == 200

    scope = storage.resolve_conv_scope(fake_drive, conv_id)
    assert scope == ("chat", conv_id)

    update_calls = [c for c in fake_pg_execute.call_args_list if "update memory_chunks" in c[0][0]]
    assert len(update_calls) == 1
    sql, params = update_calls[0][0]
    assert params == ("chat", conv_id, TEST_USER_ID, conv_id)


def test_move_chat_out_is_idempotent(client, fake_drive):
    meta = storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="Chat")
    conv_id = meta["id"]
    resp = client.post("/projects", json={"name": "Proj"})
    project_id = resp.json()["id"]

    r1 = client.delete(f"/projects/{project_id}/chats/{conv_id}")
    assert r1.status_code == 200  # already standalone -- no-op, not an error
    assert storage.resolve_conv_scope(fake_drive, conv_id) == ("chat", conv_id)


def test_move_chat_out_wrong_project_404(client, fake_drive):
    resp = client.post("/projects", json={"name": "A"})
    project_a = resp.json()["id"]
    resp = client.post("/projects", json={"name": "B"})
    project_b = resp.json()["id"]
    meta = storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="Chat")
    conv_id = meta["id"]
    client.post(f"/projects/{project_a}/chats/{conv_id}")

    resp = client.delete(f"/projects/{project_b}/chats/{conv_id}")
    assert resp.status_code == 404


def test_move_chat_out_missing_chat_404(client, fake_drive):
    resp = client.post("/projects", json={"name": "Proj"})
    project_id = resp.json()["id"]
    resp = client.delete(f"/projects/{project_id}/chats/does-not-exist")
    assert resp.status_code == 404


# ─── Post-move-out isolation + scope cache eviction ──────────────────────


def test_move_out_evicts_scope_cache_so_sibling_retrieval_loses_access(client, fake_drive):
    """The core M.5 correctness guarantee: once a chat is moved out, its
    resolved scope must reflect the new state immediately, not a stale
    in-process cache entry from before the move."""
    from app.memory import indexer

    resp = client.post("/projects", json={"name": "Proj"})
    project_id = resp.json()["id"]
    meta = storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="Chat")
    conv_id = meta["id"]
    client.post(f"/projects/{project_id}/chats/{conv_id}")

    # Warm the cache as if a turn had just been indexed under project scope.
    cached = indexer.resolve_scope(TEST_USER_ID, conv_id, drive=fake_drive)
    assert cached == ("project", project_id)

    client.delete(f"/projects/{project_id}/chats/{conv_id}")

    # Must reflect the move immediately, not the stale cached ('project', ...) entry.
    fresh = indexer.resolve_scope(TEST_USER_ID, conv_id, drive=fake_drive)
    assert fresh == ("chat", conv_id)


def test_moved_chats_new_turns_index_into_current_scope(client, fake_drive):
    """A chat's next index_turn_task call (no precomputed scope passed) must
    resolve to wherever the chat currently lives, not where it used to."""
    import asyncio
    from unittest.mock import AsyncMock

    from app.memory import indexer

    resp = client.post("/projects", json={"name": "Proj"})
    project_id = resp.json()["id"]
    meta = storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="Chat")
    conv_id = meta["id"]
    client.post(f"/projects/{project_id}/chats/{conv_id}")

    fake_add_chunk = MagicMock(return_value=1)
    with patch("app.core.drive_factory.get_drive_for_user", return_value=fake_drive):
        with patch("app.memory.embed.embed", new=AsyncMock(return_value=[0.1] * 768)):
            with patch("app.memory.index.add_chunk", fake_add_chunk):
                asyncio.run(
                    indexer.index_turn_task(
                        TEST_USER_ID, conv_id, None, [{"role": "user", "content": "post-move message"}]
                    )
                )

    assert fake_add_chunk.call_count == 1
    call = fake_add_chunk.call_args_list[0]
    assert (call[0][1], call[0][2]) == ("project", project_id)
