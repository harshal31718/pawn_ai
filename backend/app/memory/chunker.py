"""Splits a committed conversation turn into fixed-size, overlapping chunks
for RAG indexing (Phase M — memory scoping).

Token counts are approximated as len(text) // 4 (no tokenizer dependency) —
see workspace/plan/plan_memory_scoping.md §5 M.3.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.constants import MEMORY_CHUNK_OVERLAP_TOKENS, MEMORY_CHUNK_TOKENS

_CHARS_PER_TOKEN = 4
_CHUNK_CHARS = MEMORY_CHUNK_TOKENS * _CHARS_PER_TOKEN
_OVERLAP_CHARS = MEMORY_CHUNK_OVERLAP_TOKENS * _CHARS_PER_TOKEN


def chunk_turn(turn_msgs: List[Dict[str, Any]], msg_index_start: int) -> List[Dict[str, Any]]:
    """Split a list of messages (typically one committed turn: user msg +
    assistant reply) into fixed-size overlapping character chunks. Each
    source message keeps its own msg_index (msg_index_start + its position
    in turn_msgs), so a chunk always traces back to the message it came from.

    Returns chunk records shaped for both Drive (rag_chunks.jsonl) and
    Postgres (add_chunk), minus `conv_id` (the caller stamps that in, since
    chunking itself doesn't need to know which chat it's for):
      {"chunk_id": <uuid>, "msg_index": <int>, "text": <str>,
       "created_at": <iso8601>}
    """
    records: List[Dict[str, Any]] = []
    for offset, msg in enumerate(turn_msgs):
        text = (msg.get("content") or "").strip()
        if not text:
            continue
        records.extend(_chunk_text(text, msg_index_start + offset))
    return records


def _chunk_text(text: str, msg_index: int) -> List[Dict[str, Any]]:
    if len(text) <= _CHUNK_CHARS:
        return [_make_record(text, msg_index)]

    chunks: List[Dict[str, Any]] = []
    stride = max(_CHUNK_CHARS - _OVERLAP_CHARS, 1)
    start = 0
    while start < len(text):
        piece = text[start : start + _CHUNK_CHARS]
        if piece:
            chunks.append(_make_record(piece, msg_index))
        if start + _CHUNK_CHARS >= len(text):
            break
        start += stride
    return chunks


def _make_record(text: str, msg_index: int) -> Dict[str, Any]:
    return {
        "chunk_id": str(uuid.uuid4()),
        "msg_index": msg_index,
        "text": text,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
