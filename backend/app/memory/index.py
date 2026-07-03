"""Per-user memory chunk storage backed by self-hosted Postgres + pgvector.

Replaces the previous local SQLite + sqlite-vec implementation (and, before
that, Supabase). Memory chunks (conversation summaries and their 768-dim
embeddings) live in the `memory_chunks` table, scoped by `user_id`.

All operations are exception-safe: if Postgres is unreachable or not yet
configured, add_chunk() returns None (no-op) so chat continues to work without
memory. The schema (table + SQL functions) is created once via the SQL at
supabase/schema.sql (name kept for history; it's plain Postgres now).
"""

import sys
from typing import List, Optional

from app.db.postgres_client import fetchone


def add_chunk(user_id: str, conv_id: str, text: str, embedding: List[float]) -> Optional[int]:
    """
    Insert a memory chunk (text + embedding) for a user into Postgres.
    Returns the new row id, or None if the insert failed / Postgres unavailable.
    """
    try:
        row = fetchone(
            """
            insert into memory_chunks (user_id, conv_id, text, embedding)
            values (%s, %s, %s, %s)
            returning id
            """,
            (user_id, conv_id, text, embedding),
        )
        return row.get("id") if row else None
    except Exception as e:
        print(f"Failed to add memory chunk: {e}", file=sys.stderr)
        return None
