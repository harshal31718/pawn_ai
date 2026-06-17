import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

from app.constants import CONVERSATIONS_DIR

def _get_conv_dir(conv_id: str) -> Path:
    """Helper to get the conversation directory path."""
    return CONVERSATIONS_DIR / conv_id

def _ensure_conversations_dir() -> None:
    """Helper to ensure CONVERSATIONS_DIR exists."""
    CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)

def create_conversation(
    conv_id: Optional[str] = None,
    title: str = "New Chat",
    model_id: str = "gemini"
) -> Dict[str, Any]:
    """
    Creates a new conversation folder, initialises its meta.json,
    and returns the metadata dictionary.
    """
    _ensure_conversations_dir()
    if not conv_id:
        conv_id = str(uuid.uuid4())
        
    conv_dir = _get_conv_dir(conv_id)
    conv_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now(timezone.utc).isoformat()
    meta = {
        "id": conv_id,
        "title": title,
        "created_at": timestamp,
        "updated_at": timestamp,
        "model_id": model_id,
        "message_count": 0
    }
    
    meta_file = conv_dir / "meta.json"
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
        
    # Ensure messages.jsonl is created
    messages_file = conv_dir / "messages.jsonl"
    messages_file.touch(exist_ok=True)
    
    return meta

def list_conversations() -> List[Dict[str, Any]]:
    """
    Lists metadata of all conversations, sorted by updated_at descending.
    """
    _ensure_conversations_dir()
    results = []
    
    if not CONVERSATIONS_DIR.exists():
        return []
        
    for path in CONVERSATIONS_DIR.iterdir():
        if path.is_dir():
            meta_file = path / "meta.json"
            if meta_file.exists():
                try:
                    with open(meta_file, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                        results.append(meta)
                except (json.JSONDecodeError, OSError):
                    # Skip corrupt metadata files
                    pass
                    
    # Sort descending by updated_at
    results.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return results

def get_conversation_meta(conv_id: str) -> Optional[Dict[str, Any]]:
    """
    Gets metadata for a specific conversation. Returns None if not found.
    """
    meta_file = _get_conv_dir(conv_id) / "meta.json"
    if not meta_file.exists():
        return None
    try:
        with open(meta_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

def load_messages(conv_id: str) -> List[Dict[str, Any]]:
    """
    Loads all messages for a specific conversation from its messages.jsonl file.
    Returns an empty list if conversation/file does not exist.
    """
    messages_file = _get_conv_dir(conv_id) / "messages.jsonl"
    if not messages_file.exists():
        return []
        
    messages = []
    try:
        with open(messages_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except OSError:
        pass
    return messages

def append_messages(conv_id: str, new_messages: List[Dict[str, Any]]) -> None:
    """
    Appends a list of messages to the messages.jsonl file of a conversation,
    and updates the message count and updated_at timestamp in meta.json.
    """
    conv_dir = _get_conv_dir(conv_id)
    if not conv_dir.exists():
        # Auto-create if directory doesn't exist for some reason
        create_conversation(conv_id=conv_id)
        
    messages_file = conv_dir / "messages.jsonl"
    with open(messages_file, "a", encoding="utf-8") as f:
        for msg in new_messages:
            f.write(json.dumps(msg) + "\n")
            
    # Update meta.json
    meta = get_conversation_meta(conv_id)
    if meta:
        meta["message_count"] = len(load_messages(conv_id))
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        meta_file = conv_dir / "meta.json"
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

def update_conversation_title(conv_id: str, new_title: str) -> Optional[Dict[str, Any]]:
    """
    Updates the title of a conversation in its meta.json.
    """
    conv_dir = _get_conv_dir(conv_id)
    meta = get_conversation_meta(conv_id)
    if not meta:
        return None
        
    meta["title"] = new_title
    meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    meta_file = conv_dir / "meta.json"
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
        
    return meta

def delete_conversation(conv_id: str) -> None:
    """
    Deletes the folder of a specific conversation, removing all metadata and message files.
    """
    conv_dir = _get_conv_dir(conv_id)
    if conv_dir.exists() and conv_dir.is_dir():
        shutil.rmtree(conv_dir)
