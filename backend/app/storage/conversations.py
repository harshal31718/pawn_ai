"""Local filesystem conversation storage, scoped by user_id.

File layout: CONVERSATIONS_DIR / {user_id} / {conv_id} /
  meta.json        — metadata
  messages.jsonl   — append-only message log
  summary.md       — optional rolling summary

NOTE: This module is the local-filesystem implementation.
DD-2 will replace it with conversations_drive.py (Google Drive backend).
"""

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.constants import CONVERSATIONS_DIR

_ANON = "anon"


def _user_dir(user_id: Optional[str]) -> Path:
    return CONVERSATIONS_DIR / (user_id or _ANON)


def _get_conv_dir(user_id: Optional[str], conv_id: str) -> Path:
    return _user_dir(user_id) / conv_id


def create_conversation(
    user_id: Optional[str] = None,
    conv_id: Optional[str] = None,
    title: str = "New Chat",
    model_id: str = "gemini",
) -> Dict[str, Any]:
    udir = _user_dir(user_id)
    udir.mkdir(parents=True, exist_ok=True)
    if not conv_id:
        conv_id = str(uuid.uuid4())

    conv_dir = _get_conv_dir(user_id, conv_id)
    conv_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).isoformat()
    meta = {
        "id": conv_id,
        "user_id": user_id or _ANON,
        "title": title,
        "created_at": timestamp,
        "updated_at": timestamp,
        "model_id": model_id,
        "message_count": 0,
    }
    (conv_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (conv_dir / "messages.jsonl").touch(exist_ok=True)
    return meta


def list_conversations(user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    udir = _user_dir(user_id)
    udir.mkdir(parents=True, exist_ok=True)
    results = []
    for path in udir.iterdir():
        if path.is_dir():
            meta_file = path / "meta.json"
            if meta_file.exists():
                try:
                    results.append(json.loads(meta_file.read_text(encoding="utf-8")))
                except (json.JSONDecodeError, OSError):
                    pass
    results.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return results


def get_conversation_meta(conv_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    meta_file = _get_conv_dir(user_id, conv_id) / "meta.json"
    if not meta_file.exists():
        return None
    try:
        return json.loads(meta_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def load_messages(conv_id: str, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    messages_file = _get_conv_dir(user_id, conv_id) / "messages.jsonl"
    if not messages_file.exists():
        return []
    messages = []
    try:
        for line in messages_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass
    return messages


def append_messages(conv_id: str, new_messages: List[Dict[str, Any]], user_id: Optional[str] = None) -> None:
    conv_dir = _get_conv_dir(user_id, conv_id)
    if not conv_dir.exists():
        create_conversation(user_id=user_id, conv_id=conv_id)

    messages_file = conv_dir / "messages.jsonl"
    with open(messages_file, "a", encoding="utf-8") as f:
        for msg in new_messages:
            f.write(json.dumps(msg) + "\n")

    meta = get_conversation_meta(conv_id, user_id)
    if meta:
        meta["message_count"] = len(load_messages(conv_id, user_id))
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        (conv_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def update_conversation_title(conv_id: str, new_title: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conv_dir = _get_conv_dir(user_id, conv_id)
    meta = get_conversation_meta(conv_id, user_id)
    if not meta:
        return None
    meta["title"] = new_title
    meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    (conv_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def delete_conversation(conv_id: str, user_id: Optional[str] = None) -> None:
    conv_dir = _get_conv_dir(user_id, conv_id)
    if conv_dir.exists() and conv_dir.is_dir():
        shutil.rmtree(conv_dir)


def load_summary(conv_id: str, user_id: Optional[str] = None) -> Optional[str]:
    summary_file = _get_conv_dir(user_id, conv_id) / "summary.md"
    if not summary_file.exists():
        return None
    try:
        return summary_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def save_summary(conv_id: str, summary_text: str, user_id: Optional[str] = None) -> None:
    conv_dir = _get_conv_dir(user_id, conv_id)
    if not conv_dir.exists():
        create_conversation(user_id=user_id, conv_id=conv_id)
    (conv_dir / "summary.md").write_text(summary_text, encoding="utf-8")
