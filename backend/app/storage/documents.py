"""In-memory document storage, scoped by user_id.

Key format: "{user_id}:{doc_id}" so different users' uploads don't collide.
This module will be replaced by documents_drive.py (DD-3) for persistent Drive storage.
"""

from typing import Dict, Optional

_documents: Dict[str, str] = {}


def _key(user_id: Optional[str], doc_id: str) -> str:
    return f"{user_id or 'anon'}:{doc_id}"


def store_doc(doc_id: str, text: str, user_id: Optional[str] = None) -> None:
    _documents[_key(user_id, doc_id)] = text


def load_doc(doc_id: str, user_id: Optional[str] = None) -> Optional[str]:
    return _documents.get(_key(user_id, doc_id))


def clear_docs() -> None:
    _documents.clear()
