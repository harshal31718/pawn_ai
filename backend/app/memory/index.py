"""Per-user memory chunk storage backed by Supabase (PostgreSQL + pgvector).

Replaces the previous local SQLite + sqlite-vec implementation. Memory chunks
(conversation summaries and their 768-dim embeddings) live in the `memory_chunks`
table in Supabase, scoped by `user_id`.

All operations are exception-safe: if Supabase is unreachable or not yet
configured, add_chunk() returns None (no-op) so chat continues to work without
memory. The Supabase schema (table + RPC functions) is created once via the
SQL in workspace/plan — see supabase_schema.sql.
"""

import sys
from typing import List, Optional

from app.db.supabase_client import get_db


def add_chunk(user_id: str, conv_id: str, text: str, embedding: List[float]) -> Optional[int]:
    """
    Insert a memory chunk (text + embedding) for a user into Supabase.
    Returns the new row id, or None if the insert failed / Supabase unavailable.
    """
    try:
        db = get_db()
        result = (
            db.table("memory_chunks")
            .insert(
                {
                    "user_id": user_id,
                    "conv_id": conv_id,
                    "text": text,
                    "embedding": embedding,
                }
            )
            .execute()
        )
        if result.data:
            return result.data[0].get("id")
        return None
    except Exception as e:
        print(f"Failed to add memory chunk: {e}", file=sys.stderr)
        return None
