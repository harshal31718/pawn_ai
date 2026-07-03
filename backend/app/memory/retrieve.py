"""Per-user hybrid memory retrieval backed by self-hosted Postgres (pgvector + FTS).

Combines vector similarity search (pgvector `<=>`) and full-text search
(`tsvector @@ plainto_tsquery`) via two Postgres SQL functions, then fuses the
two ranked lists with Reciprocal Rank Fusion (RRF) in Python.

SQL functions (defined in supabase/schema.sql — name kept for history, it's
plain Postgres now):
  - match_memory_chunks(query_embedding, match_user_id, exclude_conv_id, match_count)
  - search_memory_chunks(query_text, match_user_id, exclude_conv_id, match_count)

Graceful degradation: if embedding fails, falls back to FTS only. If Postgres is
unreachable, returns []. Memory is always scoped by user_id.
"""

import asyncio
from typing import Any, Dict, List, Optional

from app.db.postgres_client import fetchall
from app.memory.embed import embed


async def retrieve(
    query: str,
    user_id: str,
    active_conv_id: Optional[str] = None,
    top_k: int = 3,
) -> List[Dict[str, Any]]:
    """
    Retrieve the top_k most relevant past memory chunks for a user using hybrid
    search (pgvector + Postgres FTS) fused with Reciprocal Rank Fusion (RRF).
    The active conversation is excluded to avoid surfacing the current context.
    """
    # 1. Generate query embedding (graceful fallback to FTS-only on failure)
    try:
        query_vector = await embed(query, user_id=user_id)
    except Exception:
        query_vector = None

    vec_results: List[Dict[str, Any]] = []
    fts_results: List[Dict[str, Any]] = []
    candidate_k = max(20, top_k * 4)

    # 2. Vector search candidates (pgvector cosine via SQL function)
    if query_vector:
        try:
            rows = await asyncio.to_thread(
                fetchall,
                # Explicit ::vector cast — Postgres won't implicitly cast a
                # plain array parameter to match the function's vector(768)
                # argument, so an untyped call fails to resolve the overload.
                "select * from match_memory_chunks(%s::vector, %s, %s, %s::int)",
                (query_vector, user_id, active_conv_id, candidate_k),
            )
            for r in rows:
                vec_results.append(
                    {"id": r["id"], "conv_id": r["conv_id"], "text": r["text"]}
                )
        except Exception:
            pass

    # 3. Full-text search candidates (Postgres FTS via SQL function)
    try:
        rows = await asyncio.to_thread(
            fetchall,
            "select * from search_memory_chunks(%s, %s, %s, %s::int)",
            (query, user_id, active_conv_id, candidate_k),
        )
        for r in rows:
            fts_results.append(
                {"id": r["id"], "conv_id": r["conv_id"], "text": r["text"]}
            )
    except Exception:
        pass

    # 4. Reciprocal Rank Fusion: score = sum(1 / (60 + rank)) across both lists
    scores: Dict[int, float] = {}
    docs_map: Dict[int, Dict[str, Any]] = {}

    for rank, doc in enumerate(vec_results, start=1):
        rid = doc["id"]
        scores[rid] = scores.get(rid, 0.0) + (1.0 / (60.0 + rank))
        docs_map[rid] = doc

    for rank, doc in enumerate(fts_results, start=1):
        rid = doc["id"]
        scores[rid] = scores.get(rid, 0.0) + (1.0 / (60.0 + rank))
        docs_map[rid] = doc

    sorted_ids = sorted(scores.keys(), key=lambda r: scores[r], reverse=True)
    return [docs_map[r] for r in sorted_ids[:top_k]]
