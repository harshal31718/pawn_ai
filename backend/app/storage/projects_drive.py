"""Google Drive-backed project storage (Phase M — memory scoping).

  PAWN/conversations/projects/{project_id}/
    project.json            # {id, name, description, created_at, updated_at}
    {conv_id}/               # per-chat folder, same shape as a standalone chat
      meta.json
      messages.jsonl
      summary.md
      rag_chunks.jsonl

Folder placement is the only source of scope truth — no membership table.
A chat under conversations/chats/ is standalone; a chat under
conversations/projects/{pid}/ belongs to that project. See
workspace/plan/plan_memory_scoping.md §3/§5 M.2.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.storage.drive import DriveStorage


def _projects_folder(drive: DriveStorage) -> str:
    """Return the folder ID for PAWN/conversations/projects/."""
    root = drive.get_or_create_root()
    convs = drive.get_or_create_folder("conversations", root)
    return drive.get_or_create_folder("projects", convs)


def _project_folder(drive: DriveStorage, project_id: str) -> str:
    """Return (or create) the folder ID for PAWN/conversations/projects/{project_id}/."""
    return drive.get_or_create_folder(project_id, _projects_folder(drive))


def create_project(
    drive: DriveStorage,
    project_id: Optional[str] = None,
    name: str = "New Project",
    description: str = "",
) -> Dict[str, Any]:
    """Create a project folder + project.json. Client-generated project_id
    supported so a retried request never creates a duplicate project — same
    end-to-end idempotent behavior as conversations, though conversations'
    guard lives one layer up in routes/conversations.py's `_create()` rather
    than inside create_conversation() itself; this function's guard lives
    here instead so M.5's routes/projects.py doesn't need to duplicate it."""
    if not project_id:
        project_id = str(uuid.uuid4())

    folder_id = _project_folder(drive, project_id)
    existing = drive.find_file("project.json", folder_id)
    if existing:
        try:
            return json.loads(drive.download_text(existing))
        except (json.JSONDecodeError, Exception):
            pass

    timestamp = datetime.now(timezone.utc).isoformat()
    meta = {
        "id": project_id,
        "name": name,
        "description": description,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    drive.upload_text("project.json", json.dumps(meta, indent=2), folder_id)
    return meta


def list_projects(drive: DriveStorage) -> List[Dict[str, Any]]:
    projects_folder = _projects_folder(drive)
    subfolders = drive.list_subfolders(projects_folder)
    contents = drive.read_files_in_folders([f["id"] for f in subfolders], "project.json")
    results = []
    for folder in subfolders:
        raw = contents.get(folder["id"])
        if raw is None:
            continue
        try:
            results.append(json.loads(raw))
        except (json.JSONDecodeError, Exception):
            pass
    results.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return results


def get_project_meta(drive: DriveStorage, project_id: str) -> Optional[Dict[str, Any]]:
    projects_folder = _projects_folder(drive)
    project_folder_id = drive.find_file(project_id, projects_folder)
    if not project_folder_id:
        return None
    meta_id = drive.find_file("project.json", project_folder_id)
    if not meta_id:
        return None
    try:
        return json.loads(drive.download_text(meta_id))
    except (json.JSONDecodeError, Exception):
        return None


def update_project(
    drive: DriveStorage,
    project_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Rewrites project.json only — never relocates the Drive folder
    (renames must never invalidate the drive_factory file-ID cache).
    F-10: generalized from the old rename-only `rename_project` to also cover
    the project description field; either argument left None leaves that
    field unchanged (so a pure rename and a pure description edit both go
    through this one function without clobbering the other field)."""
    projects_folder = _projects_folder(drive)
    project_folder_id = drive.find_file(project_id, projects_folder)
    if not project_folder_id:
        return None
    meta_content = drive.download_text_by_name("project.json", project_folder_id)
    if not meta_content:
        return None
    try:
        meta = json.loads(meta_content)
        if name is not None:
            meta["name"] = name
        if description is not None:
            meta["description"] = description
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        drive.upload_text("project.json", json.dumps(meta, indent=2), project_folder_id)
        return meta
    except (json.JSONDecodeError, Exception):
        return None


def delete_project(drive: DriveStorage, project_id: str) -> None:
    """Cascade delete: removes the project folder and everything inside it
    (every contained chat's meta/messages/summary/rag files included) — Drive
    permanently deletes a folder's descendants along with it when they have
    no other parent, which is always true here (decision #9)."""
    projects_folder = _projects_folder(drive)
    project_folder_id = drive.find_file(project_id, projects_folder)
    if project_folder_id:
        drive.delete_file(project_folder_id)


def list_project_chats(drive: DriveStorage, project_id: str) -> List[Dict[str, Any]]:
    """List the meta.json of every chat currently inside a project."""
    projects_folder = _projects_folder(drive)
    project_folder_id = drive.find_file(project_id, projects_folder)
    if not project_folder_id:
        return []
    subfolders = drive.list_subfolders(project_folder_id)
    contents = drive.read_files_in_folders([f["id"] for f in subfolders], "meta.json")
    results = []
    for folder in subfolders:
        raw = contents.get(folder["id"])
        if raw is None:
            continue
        try:
            results.append(json.loads(raw))
        except (json.JSONDecodeError, Exception):
            pass
    results.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return results


def move_chat(drive: DriveStorage, conv_id: str, from_parent_id: str, to_parent_id: str) -> None:
    """Relocate a chat's folder between two parents — a thin wrapper over
    drive.move_item, used for BOTH move-in (chats/ -> projects/{pid}/) and
    move-out (projects/{pid}/ -> chats/), per decision #8 (two-way moves)."""
    item_id = drive.find_file(conv_id, from_parent_id)
    if item_id:
        drive.move_item(item_id, to_parent_id, from_parent_id)
