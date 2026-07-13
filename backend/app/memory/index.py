"""Per-user memory chunk storage backed by self-hosted Postgres + pgvector.

Memory chunks (per-turn text + 768-dim embeddings) live in the
`memory_chunks` table, scoped by `(user_id, scope_type, scope_id)` per
Phase M (memory scoping) — see workspace/plan/plan_memory_scoping.md §4.
`scope_type`/`scope_id` are 'chat'/conv_id for a standalone chat or
'project'/project_id for a chat inside a project; `conv_id` is retained
as provenance (which chat actually wrote the chunk).

All operations are exception-safe: if Postgres is unreachable or not yet
configured, add_chunk() returns None (no-op) so chat continues to work without
memory. The schema (table + SQL functions) is created once via the SQL at
postgres/schema.sql (or postgres/migrations/2026-07_memory_scoping.sql on an
already-initialized volume).
"""

import sys
from typing import List, Optional

from app.db.postgres_client import fetchone


def add_chunk(
    user_id: str,
    scope_type: str,
    scope_id: str,
    conv_id: str,
    chunk_id: str,
    msg_index: Optional[int],
    text: str,
    embedding: List[float],
) -> Optional[int]:
    """
    Insert (or idempotently re-index) a memory chunk for a user into
    Postgres. Upserts on the (user_id, chunk_id) unique constraint so a
    rebuild/re-index never creates duplicate rows for the same source chunk.
    Returns the row id, or None if the write failed / Postgres unavailable.
    """
    try:
        row = fetchone(
            """
            insert into memory_chunks
                (user_id, scope_type, scope_id, conv_id, chunk_id, msg_index, text, embedding)
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (user_id, chunk_id) do update set
                scope_type = excluded.scope_type,
                scope_id   = excluded.scope_id,
                conv_id    = excluded.conv_id,
                msg_index  = excluded.msg_index,
                text       = excluded.text,
                embedding  = excluded.embedding
            returning id
            """,
            (user_id, scope_type, scope_id, conv_id, chunk_id, msg_index, text, embedding),
        )
        return row.get("id") if row else None
    except Exception as e:
        print(f"Failed to add memory chunk: {e}", file=sys.stderr)
        return None
