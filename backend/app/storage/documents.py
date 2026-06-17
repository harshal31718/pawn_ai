from typing import Dict, Optional

# In-memory document storage mapping doc_id -> extracted text content
_documents: Dict[str, str] = {}

def store_doc(doc_id: str, text: str) -> None:
    """Stores the document text by its ID."""
    _documents[doc_id] = text

def load_doc(doc_id: str) -> Optional[str]:
    """Retrieves the document text by its ID, returning None if not found."""
    return _documents.get(doc_id)

def clear_docs() -> None:
    """Clears all stored documents (useful for testing)."""
    _documents.clear()
