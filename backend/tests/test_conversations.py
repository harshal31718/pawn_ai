import json
import pytest
from unittest.mock import MagicMock, patch
from starlette.testclient import TestClient

from app.main import app
from app.storage import conversations_drive as storage
from tests.fake_drive import FakeDriveStorage

# Must match conftest.TEST_USER_ID so HTTP routes and direct storage calls agree
TEST_USER_ID = "test-user-id"


@pytest.fixture()
def fake_drive():
    return FakeDriveStorage()


@pytest.fixture()
def client(fake_drive):
    with patch("app.core.drive_factory.get_drive_for_user", return_value=fake_drive):
        with TestClient(app) as c:
            yield c


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
    assert resp.json()["title"] == "Updated Chat Title"

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


def test_delete_conversation_also_deletes_its_memory_chunks(client, fake_drive):
    """Phase M, M.3: DELETE /conversations/{id} must delete that chat's
    Postgres memory_chunks rows too (a pre-existing gap Phase M closes)."""
    meta = storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="Doomed Chat")
    conv_id = meta["id"]

    fake_execute = MagicMock()
    with patch("app.db.postgres_client.execute", fake_execute):
        resp = client.delete(f"/conversations/{conv_id}")
    assert resp.status_code == 200

    fake_execute.assert_called_once()
    sql, params = fake_execute.call_args[0]
    assert "delete from memory_chunks" in sql
    assert params == (TEST_USER_ID, conv_id)


def test_list_conversations_tags_project_scoped_chats(client, fake_drive):
    """Phase M, M.6: GET /conversations must surface every chat, standalone
    and project-scoped, each tagged with its current project_id (None for
    standalone) — the sidebar's Projects section renders from this single
    list rather than a per-project round trip."""
    from app.storage import projects_drive

    standalone = storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="Standalone")
    resp = client.post("/projects", json={"name": "Proj"})
    project_id = resp.json()["id"]
    in_project = storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="In Project")
    projects_drive.move_chat(
        fake_drive,
        in_project["id"],
        storage._chats_folder(fake_drive),
        projects_drive._project_folder(fake_drive, project_id),
    )

    resp = client.get("/conversations")
    assert resp.status_code == 200
    by_id = {m["id"]: m for m in resp.json()}
    assert by_id[standalone["id"]]["project_id"] is None
    assert by_id[in_project["id"]]["project_id"] == project_id


def test_conversations_require_drive_when_unavailable():
    """No local fallback anymore — if Drive isn't linked, the request must
    fail clearly (412 not_configured) instead of silently degrading."""
    with patch("app.core.drive_factory.get_drive_for_user", return_value=None):
        with TestClient(app) as c:
            resp = c.get("/conversations")
    assert resp.status_code == 412
    assert resp.json()["code"] == "not_configured"


def test_chat_persistence_saves_to_disk(client, fake_drive):
    """When a chat has conversation_id, messages must be saved via Drive."""
    meta = storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="Active Chat")
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
                "conversation_id": conv_id,
            },
        ) as resp:
            resp.read()

    messages = storage.load_messages(fake_drive, conv_id)
    assert len(messages) == 2
    assert messages[0] == {"role": "user", "content": "How are you?"}
    assert messages[1] == {"role": "assistant", "content": "Response from AI."}

    meta_updated = storage.get_conversation_meta(fake_drive, conv_id)
    assert meta_updated["message_count"] == 2


def test_chat_auto_titling_trigger(client, fake_drive):
    """The first response to a 'New Chat' must trigger auto-titling background task."""
    meta = storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="New Chat")
    conv_id = meta["id"]

    async def mock_stream(*args, **kwargs):
        for token in ["Generated", " Title", " Output"]:
            yield token

    with patch("app.core.normalize.stream_llm", side_effect=mock_stream):
        with client.stream(
            "POST",
            "/chat",
            json={
                "messages": [{"role": "user", "content": "My prompt here"}],
                "conversation_id": conv_id,
            },
        ) as resp:
            resp.read()

    updated_meta = storage.get_conversation_meta(fake_drive, conv_id)
    assert updated_meta["title"] == "Generated Title Output"


def test_chat_lazy_creates_unknown_conversation(client, fake_drive):
    """POST /chat with a client-owned conversation_id that doesn't exist yet must
    lazy-create it (no 404) and persist the turn — the optimistic-UI fail-proof path."""
    conv_id = "client-owned-conv-abc123"

    async def mock_stream(*args, **kwargs):
        yield "Hi"
        yield " there"

    with patch("app.core.normalize.stream_llm", side_effect=mock_stream):
        with client.stream(
            "POST",
            "/chat",
            json={
                "messages": [{"role": "user", "content": "hello"}],
                "conversation_id": conv_id,
            },
        ) as resp:
            assert resp.status_code == 200
            resp.read()

    meta = storage.get_conversation_meta(fake_drive, conv_id)
    assert meta is not None
    assert meta["id"] == conv_id

    messages = storage.load_messages(fake_drive, conv_id)
    assert len(messages) == 2
    assert messages[0] == {"role": "user", "content": "hello"}
    assert messages[1]["role"] == "assistant"
