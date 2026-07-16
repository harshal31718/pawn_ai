"""Tests for Phase M's Drive storage layer: the new chats//projects/ layout,
project CRUD, two-way chat moves, and the one-time legacy-folder migration.

All tests run against FakeDriveStorage (in-memory) — no real Drive API calls,
per testing.md.
"""

import pytest

from app.storage import conversations_drive as conv_storage
from app.storage import projects_drive
from tests.fake_drive import FakeDriveStorage

TEST_USER_ID = "test-user-id"


@pytest.fixture()
def fake_drive():
    return FakeDriveStorage()


# ---------------------------------------------------------------------------
# New chats/ layout
# ---------------------------------------------------------------------------


def test_new_conversation_lands_under_chats_folder(fake_drive):
    meta = conv_storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="Hi")
    conv_id = meta["id"]

    root = fake_drive.get_or_create_root()
    convs = fake_drive.get_or_create_folder("conversations", root)
    chats = fake_drive.get_or_create_folder("chats", convs)
    assert fake_drive.find_file(conv_id, chats) is not None

    # Not created directly under conversations/ (the pre-Phase-M layout).
    direct_children = fake_drive.list_subfolders(convs)
    assert any(f["name"] == "chats" for f in direct_children)
    assert not any(f["name"] == conv_id for f in direct_children if f["name"] != "chats")


def test_list_conversations_only_returns_standalone_chats(fake_drive):
    conv_storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="Standalone")
    project = projects_drive.create_project(fake_drive, name="Proj")
    projects_folder_id = fake_drive.find_file(
        project["id"], projects_drive._projects_folder(fake_drive)
    )
    # A chat created directly inside a project folder (simulating M.5's
    # born-in-project flow) must not show up in the flat chats list.
    fake_drive.get_or_create_folder("proj-chat-1", projects_folder_id)

    results = conv_storage.list_conversations(fake_drive)
    assert len(results) == 1
    assert results[0]["title"] == "Standalone"


# ---------------------------------------------------------------------------
# Legacy migration
# ---------------------------------------------------------------------------


def test_legacy_folder_migrates_on_first_access(fake_drive, capsys):
    # Build a legacy tree directly: PAWN/conversations/{conv_id}/meta.json,
    # bypassing create_conversation (which always writes the new layout).
    root = fake_drive.get_or_create_root()
    convs = fake_drive.get_or_create_folder("conversations", root)
    legacy_folder = fake_drive.get_or_create_folder("legacy-conv-1", convs)
    fake_drive.upload_text("meta.json", '{"id": "legacy-conv-1", "title": "Old Chat"}', legacy_folder)

    results = conv_storage.list_conversations(fake_drive)

    assert len(results) == 1
    assert results[0]["id"] == "legacy-conv-1"

    chats = fake_drive.get_or_create_folder("chats", convs)
    assert fake_drive.find_file("legacy-conv-1", chats) is not None
    # No longer a direct child of conversations/ once migrated.
    direct_children = [f["name"] for f in fake_drive.list_subfolders(convs)]
    assert direct_children.count("legacy-conv-1") == 0

    captured = capsys.readouterr()
    assert "legacy-conv-1" in captured.err
    assert "memory-scoping migration" in captured.err


def test_migration_is_idempotent_across_multiple_calls(fake_drive):
    root = fake_drive.get_or_create_root()
    convs = fake_drive.get_or_create_folder("conversations", root)
    legacy_folder = fake_drive.get_or_create_folder("legacy-conv-2", convs)
    fake_drive.upload_text("meta.json", '{"id": "legacy-conv-2"}', legacy_folder)

    conv_storage.list_conversations(fake_drive)
    # Second call must not error or duplicate/move anything further.
    results = conv_storage.list_conversations(fake_drive)
    assert len(results) == 1


# ---------------------------------------------------------------------------
# Projects CRUD
# ---------------------------------------------------------------------------


def test_create_project_creates_folder_and_json(fake_drive):
    meta = projects_drive.create_project(fake_drive, name="Research")
    assert meta["name"] == "Research"
    assert "id" in meta and "created_at" in meta and "updated_at" in meta

    fetched = projects_drive.get_project_meta(fake_drive, meta["id"])
    assert fetched == meta


def test_create_project_idempotent_on_client_id(fake_drive):
    first = projects_drive.create_project(fake_drive, project_id="fixed-id", name="A")
    second = projects_drive.create_project(fake_drive, project_id="fixed-id", name="A")
    assert first == second

    projects_folder = projects_drive._projects_folder(fake_drive)
    assert len(fake_drive.list_subfolders(projects_folder)) == 1


def test_list_projects(fake_drive):
    projects_drive.create_project(fake_drive, name="One")
    projects_drive.create_project(fake_drive, name="Two")
    results = projects_drive.list_projects(fake_drive)
    assert {p["name"] for p in results} == {"One", "Two"}


def test_rename_project_does_not_move_folder(fake_drive):
    meta = projects_drive.create_project(fake_drive, name="Old Name")
    projects_folder = projects_drive._projects_folder(fake_drive)
    folder_id_before = fake_drive.find_file(meta["id"], projects_folder)

    updated = projects_drive.update_project(fake_drive, meta["id"], name="New Name")

    assert updated["name"] == "New Name"
    folder_id_after = fake_drive.find_file(meta["id"], projects_folder)
    assert folder_id_before == folder_id_after


def test_create_project_with_description(fake_drive):
    meta = projects_drive.create_project(fake_drive, name="Has Desc", description="A short blurb")
    assert meta["description"] == "A short blurb"
    fetched = projects_drive.get_project_meta(fake_drive, meta["id"])
    assert fetched["description"] == "A short blurb"


def test_update_project_description_only_leaves_name_unchanged(fake_drive):
    meta = projects_drive.create_project(fake_drive, name="Keep This Name")
    updated = projects_drive.update_project(fake_drive, meta["id"], description="New description")
    assert updated["name"] == "Keep This Name"
    assert updated["description"] == "New description"


def test_update_project_name_only_leaves_description_unchanged(fake_drive):
    meta = projects_drive.create_project(fake_drive, name="Old", description="Keep this")
    updated = projects_drive.update_project(fake_drive, meta["id"], name="New")
    assert updated["name"] == "New"
    assert updated["description"] == "Keep this"


def test_delete_project_cascades_to_contained_chats(fake_drive):
    project = projects_drive.create_project(fake_drive, name="Doomed")
    projects_folder = projects_drive._projects_folder(fake_drive)
    project_folder_id = fake_drive.find_file(project["id"], projects_folder)
    chat_folder_id = fake_drive.get_or_create_folder("chat-in-project", project_folder_id)
    fake_drive.upload_text("meta.json", "{}", chat_folder_id)

    projects_drive.delete_project(fake_drive, project["id"])

    assert projects_drive.get_project_meta(fake_drive, project["id"]) is None
    assert chat_folder_id not in fake_drive._folders
    assert fake_drive.find_file(project["id"], projects_folder) is None


def test_list_project_chats(fake_drive):
    project = projects_drive.create_project(fake_drive, name="P")
    projects_folder = projects_drive._projects_folder(fake_drive)
    project_folder_id = fake_drive.find_file(project["id"], projects_folder)
    chat_folder_id = fake_drive.get_or_create_folder("chat-1", project_folder_id)
    fake_drive.upload_text("meta.json", '{"id": "chat-1", "title": "In Project"}', chat_folder_id)

    chats = projects_drive.list_project_chats(fake_drive, project["id"])
    assert len(chats) == 1
    assert chats[0]["title"] == "In Project"


# ---------------------------------------------------------------------------
# Two-way chat moves
# ---------------------------------------------------------------------------


def test_move_chat_in_relocates_and_is_findable_via_locate(fake_drive):
    meta = conv_storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="Movable")
    conv_id = meta["id"]
    project = projects_drive.create_project(fake_drive, name="Target")

    chats_folder = conv_storage._chats_folder(fake_drive)
    projects_folder = projects_drive._projects_folder(fake_drive)
    project_folder_id = fake_drive.find_file(project["id"], projects_folder)

    projects_drive.move_chat(fake_drive, conv_id, chats_folder, project_folder_id)

    # No longer directly under chats/...
    assert fake_drive.find_file(conv_id, chats_folder) is None
    # ...but conversations_drive's generic locator still finds it (now inside the project).
    assert conv_storage._locate_conv_folder(fake_drive, conv_id) is not None
    assert conv_storage.get_conversation_meta(fake_drive, conv_id)["title"] == "Movable"

    # And it no longer appears in the flat standalone list.
    assert conv_id not in [c["id"] for c in conv_storage.list_conversations(fake_drive)]
    # But does appear as a project chat.
    assert conv_id in [c["id"] for c in projects_drive.list_project_chats(fake_drive, project["id"])]


def test_move_chat_out_returns_it_to_standalone(fake_drive):
    meta = conv_storage.create_conversation(fake_drive, user_id=TEST_USER_ID, title="Round Trip")
    conv_id = meta["id"]
    project = projects_drive.create_project(fake_drive, name="Target")

    chats_folder = conv_storage._chats_folder(fake_drive)
    projects_folder = projects_drive._projects_folder(fake_drive)
    project_folder_id = fake_drive.find_file(project["id"], projects_folder)

    projects_drive.move_chat(fake_drive, conv_id, chats_folder, project_folder_id)
    # Move back out.
    projects_drive.move_chat(fake_drive, conv_id, project_folder_id, chats_folder)

    assert fake_drive.find_file(conv_id, chats_folder) is not None
    assert conv_id in [c["id"] for c in conv_storage.list_conversations(fake_drive)]
    assert conv_id not in [c["id"] for c in projects_drive.list_project_chats(fake_drive, project["id"])]


def test_moved_chat_still_appends_messages_correctly(fake_drive):
    """A chat that's moved into a project must keep working for reads/writes
    (append_messages must locate it in its new home, not silently recreate a
    stray empty folder back under chats/)."""
    meta = conv_storage.create_conversation(fake_drive, user_id=TEST_USER_ID)
    conv_id = meta["id"]
    project = projects_drive.create_project(fake_drive, name="Target")
    chats_folder = conv_storage._chats_folder(fake_drive)
    projects_folder = projects_drive._projects_folder(fake_drive)
    project_folder_id = fake_drive.find_file(project["id"], projects_folder)
    projects_drive.move_chat(fake_drive, conv_id, chats_folder, project_folder_id)

    conv_storage.append_messages(fake_drive, conv_id, [{"role": "user", "content": "hi"}])

    messages = conv_storage.load_messages(fake_drive, conv_id)
    assert len(messages) == 1
    # Must not have created a duplicate empty folder back under chats/.
    assert fake_drive.find_file(conv_id, chats_folder) is None


# ---------------------------------------------------------------------------
# Per-chat rag_chunks.jsonl
# ---------------------------------------------------------------------------


def test_load_rag_chunks_empty_by_default(fake_drive):
    meta = conv_storage.create_conversation(fake_drive, user_id=TEST_USER_ID)
    assert conv_storage.load_rag_chunks(fake_drive, meta["id"]) == []


def test_append_and_load_rag_chunks_roundtrip(fake_drive):
    meta = conv_storage.create_conversation(fake_drive, user_id=TEST_USER_ID)
    conv_id = meta["id"]
    chunk = {
        "chunk_id": "11111111-1111-1111-1111-111111111111",
        "conv_id": conv_id,
        "msg_index": 0,
        "text": "hello world",
        "created_at": "2026-07-13T00:00:00+00:00",
    }

    conv_storage.append_rag_chunks(fake_drive, conv_id, [chunk])
    loaded = conv_storage.load_rag_chunks(fake_drive, conv_id)

    assert loaded == [chunk]

    # A second append must accumulate, not overwrite.
    chunk2 = {**chunk, "chunk_id": "22222222-2222-2222-2222-222222222222", "msg_index": 1}
    conv_storage.append_rag_chunks(fake_drive, conv_id, [chunk2])
    loaded_again = conv_storage.load_rag_chunks(fake_drive, conv_id)
    assert len(loaded_again) == 2
