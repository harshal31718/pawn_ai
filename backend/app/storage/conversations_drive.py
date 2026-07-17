"""Google Drive-backed conversation storage.

  PAWN/conversations/chats/{conv_id}/meta.json
  PAWN/conversations/chats/{conv_id}/messages.jsonl
  PAWN/conversations/chats/{conv_id}/summary.md
  PAWN/conversations/chats/{conv_id}/rag_chunks.jsonl   # NEW (Phase M) — chunk
                                                          # source of truth for
                                                          # this chat's RAG

A chat can also live inside a project instead of chats/ (see
projects_drive.py): PAWN/conversations/projects/{project_id}/{conv_id}/...
Folder placement alone determines scope — standalone vs. project — per
workspace/plan/plan_memory_scoping.md §3 (no membership table).

NOTE: append_messages/append_rag_chunks download the existing file, append
      lines, and re-upload (Drive doesn't support partial append). This is
      acceptable for normal usage but inefficient for very high message/chunk
      counts (bounded per-chat, same growth class as before Phase M).
"""

import json
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.storage.drive import DriveStorage
from app.storage import projects_drive
from app.storage.projects_drive import _projects_folder

# Attribute name used to memoize "already checked for legacy layout" directly
# on the DriveStorage instance (not a module-level id()-keyed cache -- id()
# values get reused by CPython's allocator once a cached-per-user instance is
# evicted/GC'd, which could silently skip a real user's migration and hide
# their pre-Phase-M conversations forever). No flag file lives on Drive
# either (migration state is inferred purely from folder layout, per plan
# decision #10) -- this in-memory attribute just avoids re-scanning on every
# call within one instance's lifetime (DriveStorage is itself cached per user
# by drive_factory, so this is effectively once per user per cache TTL).
_LEGACY_CHECKED_ATTR = "_pawn_legacy_migration_checked"


def _root_convs_folder(drive: DriveStorage) -> str:
    """Return the folder ID for PAWN/conversations/ itself — the parent of
    both chats/ and projects/, and (pre-migration) of legacy conv_id folders."""
    root = drive.get_or_create_root()
    return drive.get_or_create_folder("conversations", root)


def _migrate_legacy_conversations(drive: DriveStorage) -> None:
    """One-time-per-instance migration: PAWN/conversations/{conv_id}/ (legacy,
    pre-Phase-M layout) -> PAWN/conversations/chats/{conv_id}/. Runs
    automatically on first access per user; idempotent (a conversation found
    at the legacy path is migrated on access, and there's nothing left to
    move on a later pass). See plan_memory_scoping.md M.2."""
    if getattr(drive, _LEGACY_CHECKED_ATTR, False):
        return
    setattr(drive, _LEGACY_CHECKED_ATTR, True)

    convs_folder = _root_convs_folder(drive)
    chats_folder = drive.get_or_create_folder("chats", convs_folder)
    for folder in drive.list_subfolders(convs_folder):
        if folder["name"] in ("chats", "projects"):
            continue
        drive.move_item(folder["id"], chats_folder, convs_folder)
        print(
            f"[memory-scoping migration] moved legacy conversation folder "
            f"{folder['name']!r} -> conversations/chats/",
            file=sys.stderr,
        )


def _chats_folder(drive: DriveStorage) -> str:
    """Return the folder ID for PAWN/conversations/chats/."""
    _migrate_legacy_conversations(drive)
    convs_folder = _root_convs_folder(drive)
    return drive.get_or_create_folder("chats", convs_folder)


# Back-compat name used throughout this module's read paths below.
_convs_folder = _chats_folder


def _conv_folder(drive: DriveStorage, conv_id: str) -> str:
    """Return (or create) a chat's own subfolder under chats/. Used only at
    creation time — new chats are always born standalone. To find a chat that
    may already live inside a project, use _locate_conv_folder instead."""
    return drive.get_or_create_folder(conv_id, _chats_folder(drive))


def _locate_conv_folder(drive: DriveStorage, conv_id: str) -> Optional[str]:
    """Find a chat's current folder wherever its scope places it: standalone
    (chats/{id}) or inside a project (projects/{pid}/{id}). Folder placement
    is the only source of scope truth (decisions #7/#8 in
    plan_memory_scoping.md) — there is no membership table to consult.

    Scaling note: the project fallback below costs up to 1 + num_projects
    Drive calls per lookup (a Drive `find_file` per project) since there's no
    membership table to jump straight to the right one. Accepted tradeoff per
    the plan's explicit "no membership table" decision; revisit if a user's
    project count ever makes this a real latency/quota concern."""
    chats_folder = _chats_folder(drive)
    fid = drive.find_file(conv_id, chats_folder)
    if fid:
        return fid
    projects_folder = _projects_folder(drive)
    for project in drive.list_subfolders(projects_folder):
        fid = drive.find_file(conv_id, project["id"])
        if fid:
            return fid
    return None


def resolve_conv_scope(drive: DriveStorage, conv_id: str) -> Optional[tuple]:
    """Return ('chat', conv_id) or ('project', project_id) based on where the
    chat's folder currently lives — folder placement is the sole source of
    scope truth (no membership table), same walk as _locate_conv_folder but
    returning the scope tuple instead of the folder id. Returns None if the
    chat doesn't exist anywhere (e.g. raced with a delete). Used by
    memory/indexer.py's resolve_scope (Phase M, M.3)."""
    chats_folder = _chats_folder(drive)
    if drive.find_file(conv_id, chats_folder):
        return ("chat", conv_id)
    projects_folder = _projects_folder(drive)
    for project in drive.list_subfolders(projects_folder):
        # project["id"] is Drive's internal folder id (needed to query its
        # contents below); project["name"] is the project_id itself, since
        # project folders are named `<id>` only (see module docstring).
        if drive.find_file(conv_id, project["id"]):
            return ("project", project["name"])
    return None


def _conv_folder_for_write(drive: DriveStorage, conv_id: str) -> str:
    """Locate a chat's current folder for writes (append/rename/summary);
    falls back to creating it fresh under chats/ only if it genuinely doesn't
    exist anywhere yet (i.e. this is effectively a create)."""
    fid = _locate_conv_folder(drive, conv_id)
    return fid or _conv_folder(drive, conv_id)


def create_conversation(
    drive: DriveStorage,
    user_id: str,
    conv_id: Optional[str] = None,
    title: str = "New Chat",
    model_id: str = "gemini",
) -> Dict[str, Any]:
    if not conv_id:
        conv_id = str(uuid.uuid4())

    folder_id = _conv_folder(drive, conv_id)
    timestamp = datetime.now(timezone.utc).isoformat()
    meta = {
        "id": conv_id,
        "user_id": user_id,
        "title": title,
        "created_at": timestamp,
        "updated_at": timestamp,
        "model_id": model_id,
        "message_count": 0,
    }
    drive.upload_text("meta.json", json.dumps(meta, indent=2), folder_id)
    drive.upload_text("messages.jsonl", "", folder_id)
    return meta


def list_conversations(drive: DriveStorage) -> List[Dict[str, Any]]:
    """Standalone chats only (chats/) — project chats are listed per-project
    via projects_drive.list_project_chats."""
    convs_folder = _convs_folder(drive)
    subfolders = drive.list_subfolders(convs_folder)
    contents = drive.read_files_in_folders([f["id"] for f in subfolders], "meta.json")
    results = []
    for folder in subfolders:
        raw = contents.get(folder["id"])
        if raw is None:
            continue
        try:
            results.append(json.loads(raw))
        except Exception as exc:
            print(f"list_conversations: skipping {folder['id']}, meta.json parse failed: {exc}", file=sys.stderr)
    results.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return results


def list_all_conversations(drive: DriveStorage) -> List[Dict[str, Any]]:
    """Every chat, standalone and project-scoped, each meta tagged with its
    current `project_id` (None for standalone) — derived purely from folder
    placement, the same walk resolve_conv_scope uses. `GET /conversations`
    (routes/conversations.py) uses this so the sidebar's Projects section
    (Phase M, M.6) can render each project's chat list without a second
    per-project round trip."""
    results = list_conversations(drive)
    for meta in results:
        meta["project_id"] = None

    projects_folder = _projects_folder(drive)
    for project in drive.list_subfolders(projects_folder):
        project_id = project["name"]  # project folders are named `<id>` only
        for meta in projects_drive.list_project_chats(drive, project_id):
            meta["project_id"] = project_id
            results.append(meta)

    results.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return results


def get_conversation_meta(drive: DriveStorage, conv_id: str) -> Optional[Dict[str, Any]]:
    conv_folder_id = _locate_conv_folder(drive, conv_id)
    if not conv_folder_id:
        return None
    meta_id = drive.find_file("meta.json", conv_folder_id)
    if not meta_id:
        return None
    try:
        return json.loads(drive.download_text(meta_id))
    except Exception as exc:
        print(f"get_conversation_meta({conv_id}): meta.json read/parse failed, treating as not found: {exc}", file=sys.stderr)
        return None


def add_attached_doc(drive: DriveStorage, conv_id: str, doc_id: str, filename: str = "") -> None:
    """Record that a document was uploaded/indexed into this chat's scope, in
    meta.json's `attached_docs` list (`{"doc_id", "filename"}` records).
    Persisted on Drive (not just Postgres) so rebuild_index can rediscover a
    scope's documents even after a full Postgres wipe — Drive layout is
    always the source of truth (Phase A / A.4, mirrors Phase M's Drive-first
    design). `filename` lets doc_search label results by their source file."""
    conv_folder_id = _locate_conv_folder(drive, conv_id)
    if not conv_folder_id:
        return
    meta_id = drive.find_file("meta.json", conv_folder_id)
    if not meta_id:
        return
    try:
        meta = json.loads(drive.download_text(meta_id))
    except Exception as exc:
        print(f"add_attached_doc({conv_id}, {doc_id}): meta.json read/parse failed, doc not recorded: {exc}", file=sys.stderr)
        return
    attached = meta.get("attached_docs", [])
    if any(d.get("doc_id") == doc_id for d in attached if isinstance(d, dict)):
        return
    attached.append({"doc_id": doc_id, "filename": filename})
    meta["attached_docs"] = attached
    meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    drive.upload_text("meta.json", json.dumps(meta, indent=2), conv_folder_id)


def get_attached_docs(drive: DriveStorage, conv_id: str) -> List[Dict[str, str]]:
    """Return the `{"doc_id", "filename"}` records attached to this chat (via
    add_attached_doc), or [] if none / the chat doesn't exist."""
    meta = get_conversation_meta(drive, conv_id)
    if not meta:
        return []
    return meta.get("attached_docs", [])


def load_messages(drive: DriveStorage, conv_id: str) -> List[Dict[str, Any]]:
    conv_folder_id = _locate_conv_folder(drive, conv_id)
    if not conv_folder_id:
        return []
    content = drive.download_text_by_name("messages.jsonl", conv_folder_id)
    if not content:
        return []
    messages = []
    for line in content.splitlines():
        line = line.strip()
        if line:
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return messages


def append_messages(
    drive: DriveStorage, conv_id: str, new_messages: List[Dict[str, Any]]
) -> None:
    folder_id = _conv_folder_for_write(drive, conv_id)
    existing = drive.download_text_by_name("messages.jsonl", folder_id) or ""
    appended = existing + "".join(json.dumps(m) + "\n" for m in new_messages)
    drive.upload_text("messages.jsonl", appended, folder_id)

    # Update meta
    meta_content = drive.download_text_by_name("meta.json", folder_id)
    if meta_content:
        try:
            meta = json.loads(meta_content)
            all_messages = []
            for line in appended.splitlines():
                line = line.strip()
                if line:
                    try:
                        all_messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            meta["message_count"] = len(all_messages)
            meta["updated_at"] = datetime.now(timezone.utc).isoformat()
            drive.upload_text("meta.json", json.dumps(meta, indent=2), folder_id)
        except Exception as exc:
            print(f"append_messages({conv_id}): meta.json update failed, message_count/updated_at now stale: {exc}", file=sys.stderr)


def update_conversation_title(
    drive: DriveStorage, conv_id: str, new_title: str
) -> Optional[Dict[str, Any]]:
    folder_id = _conv_folder_for_write(drive, conv_id)
    meta_content = drive.download_text_by_name("meta.json", folder_id)
    if not meta_content:
        return None
    try:
        meta = json.loads(meta_content)
        meta["title"] = new_title
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        drive.upload_text("meta.json", json.dumps(meta, indent=2), folder_id)
        return meta
    except Exception as exc:
        print(f"update_conversation_title({conv_id}): meta.json read/parse/write failed: {exc}", file=sys.stderr)
        return None


def delete_conversation(drive: DriveStorage, conv_id: str) -> None:
    conv_folder_id = _locate_conv_folder(drive, conv_id)
    if conv_folder_id:
        drive.delete_file(conv_folder_id)


def load_summary(drive: DriveStorage, conv_id: str) -> Optional[str]:
    conv_folder_id = _locate_conv_folder(drive, conv_id)
    if not conv_folder_id:
        return None
    content = drive.download_text_by_name("summary.md", conv_folder_id)
    return content.strip() if content else None


def save_summary(drive: DriveStorage, conv_id: str, summary_text: str) -> None:
    folder_id = _conv_folder_for_write(drive, conv_id)
    drive.upload_text("summary.md", summary_text, folder_id)


def load_rag_chunks(drive: DriveStorage, conv_id: str) -> List[Dict[str, Any]]:
    """Read a chat's own rag_chunks.jsonl — the Drive source of truth for its
    RAG index (Postgres memory_chunks is a derived, rebuildable copy)."""
    conv_folder_id = _locate_conv_folder(drive, conv_id)
    if not conv_folder_id:
        return []
    content = drive.download_text_by_name("rag_chunks.jsonl", conv_folder_id)
    if not content:
        return []
    chunks = []
    for line in content.splitlines():
        line = line.strip()
        if line:
            try:
                chunks.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return chunks


def append_rag_chunks(
    drive: DriveStorage, conv_id: str, new_chunks: List[Dict[str, Any]]
) -> None:
    """Append chunk records to a chat's own rag_chunks.jsonl (full-file
    rewrite, batched per turn — Drive has no partial append; bounded by this
    one chat's own history, same growth class as messages.jsonl)."""
    if not new_chunks:
        return
    folder_id = _conv_folder_for_write(drive, conv_id)
    existing = drive.download_text_by_name("rag_chunks.jsonl", folder_id) or ""
    appended = existing + "".join(json.dumps(c) + "\n" for c in new_chunks)
    drive.upload_text("rag_chunks.jsonl", appended, folder_id)
