"""Google Drive-backed conversation storage.

Same interface as conversations.py but reads/writes from the user's Drive:
  PAWN/conversations/{conv_id}/meta.json
  PAWN/conversations/{conv_id}/messages.jsonl
  PAWN/conversations/{conv_id}/summary.md

NOTE: append_messages downloads the existing file, appends lines, and re-uploads
      (Drive doesn't support partial append). This is acceptable for normal usage
      but inefficient for very high message counts.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.storage.drive import DriveStorage


def _conv_folder(drive: DriveStorage, conv_id: str) -> str:
    """Return the folder ID for PAWN/conversations/{conv_id}/."""
    root = drive.get_or_create_root()
    convs_folder = drive.get_or_create_folder("conversations", root)
    return drive.get_or_create_folder(conv_id, convs_folder)


def _convs_folder(drive: DriveStorage) -> str:
    """Return the folder ID for PAWN/conversations/."""
    root = drive.get_or_create_root()
    return drive.get_or_create_folder("conversations", root)


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
    convs_folder = _convs_folder(drive)
    subfolders = drive.list_subfolders(convs_folder)
    results = []
    for folder in subfolders:
        meta_id = drive.find_file("meta.json", folder["id"])
        if meta_id:
            try:
                meta = json.loads(drive.download_text(meta_id))
                results.append(meta)
            except (json.JSONDecodeError, Exception):
                pass
    results.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return results


def get_conversation_meta(drive: DriveStorage, conv_id: str) -> Optional[Dict[str, Any]]:
    convs_folder = _convs_folder(drive)
    conv_folder_id = drive.find_file(conv_id, convs_folder)
    if not conv_folder_id:
        return None
    meta_id = drive.find_file("meta.json", conv_folder_id)
    if not meta_id:
        return None
    try:
        return json.loads(drive.download_text(meta_id))
    except (json.JSONDecodeError, Exception):
        return None


def load_messages(drive: DriveStorage, conv_id: str) -> List[Dict[str, Any]]:
    convs_folder = _convs_folder(drive)
    conv_folder_id = drive.find_file(conv_id, convs_folder)
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
    folder_id = _conv_folder(drive, conv_id)
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
        except (json.JSONDecodeError, Exception):
            pass


def update_conversation_title(
    drive: DriveStorage, conv_id: str, new_title: str
) -> Optional[Dict[str, Any]]:
    folder_id = _conv_folder(drive, conv_id)
    meta_content = drive.download_text_by_name("meta.json", folder_id)
    if not meta_content:
        return None
    try:
        meta = json.loads(meta_content)
        meta["title"] = new_title
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        drive.upload_text("meta.json", json.dumps(meta, indent=2), folder_id)
        return meta
    except (json.JSONDecodeError, Exception):
        return None


def delete_conversation(drive: DriveStorage, conv_id: str) -> None:
    convs_folder = _convs_folder(drive)
    conv_folder_id = drive.find_file(conv_id, convs_folder)
    if conv_folder_id:
        drive.delete_file(conv_folder_id)


def load_summary(drive: DriveStorage, conv_id: str) -> Optional[str]:
    convs_folder = _convs_folder(drive)
    conv_folder_id = drive.find_file(conv_id, convs_folder)
    if not conv_folder_id:
        return None
    content = drive.download_text_by_name("summary.md", conv_folder_id)
    return content.strip() if content else None


def save_summary(drive: DriveStorage, conv_id: str, summary_text: str) -> None:
    folder_id = _conv_folder(drive, conv_id)
    drive.upload_text("summary.md", summary_text, folder_id)
