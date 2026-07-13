"""Per-user hybrid memory retrieval, scoped strictly within one scope
(Phase M — memory scoping).

Combines vector similarity search (pgvector `<=>`) and full-text search
(`tsvector @@ plainto_tsquery`) via two Postgres SQL functions
(`match_scoped_chunks`/`search_scoped_chunks`, defined in
postgres/schema.sql), then fuses the two ranked lists with Reciprocal Rank
Fusion (RRF) in Python.

Retrieval never crosses a scope boundary: a query against `('chat', conv_id)`
can only ever surface chunks written under that exact scope, and likewise for
`('project', project_id)`. This equality filter (the inverse of the old
exclude-active-conv semantics) is the isolation guarantee this plan exists
for — see workspace/plan/plan_memory_scoping.md §5 M.4.

Graceful degradation: if embedding fails, falls back to FTS only. If Postgres
is unreachable, returns [].
"""

import asyncio
from typing import Any, Dict, List, Optional

from app.constants import MEMORY_TOP_K
from app.db.postgres_client import fetchall
from app.memory.embed import embed


async def retrieve(
    query: str,
    user_id: str,
    scope_type: str,
    scope_id: str,
    top_k: int = MEMORY_TOP_K,
) -> List[Dict[str, Any]]:
    """
    Retrieve the top_k most relevant memory chunks within exactly one scope
    using hybrid search (pgvector + Postgres FTS) fused with RRF. Phase M
    always queries `kind='message'` (the `kind`/`doc_id` machinery is inert
    until the follow-on plan_chat_agent_refinement.md adds document indexing).
    """
    try:
        query_vector = await embed(query, user_id=user_id)
    except Exception:
        query_vector = None

    vec_results: List[Dict[str, Any]] = []
    fts_results: List[Dict[str, Any]] = []
    candidate_k = max(20, top_k * 4)

    # 1. Vector search candidates (pgvector cosine via SQL function)
    if query_vector:
        try:
            rows = await asyncio.to_thread(
                fetchall,
                # Explicit ::vector cast — Postgres won't implicitly cast a
                # plain array parameter to match the function's vector(768)
                # argument, so an untyped call fails to resolve the overload.
                "select * from match_scoped_chunks(%s::vector, %s, %s, %s, %s, %s::int)",
                (query_vector, user_id, scope_type, scope_id, "message", candidate_k),
            )
            for r in rows:
                vec_results.append(
                    {"id": r["id"], "conv_id": r["conv_id"], "text": r["text"]}
                )
        except Exception:
            pass

    # 2. Full-text search candidates (Postgres FTS via SQL function)
    try:
        rows = await asyncio.to_thread(
            fetchall,
            "select * from search_scoped_chunks(%s, %s, %s, %s, %s, %s::int)",
            (query, user_id, scope_type, scope_id, "message", candidate_k),
        )
        for r in rows:
            fts_results.append(
                {"id": r["id"], "conv_id": r["conv_id"], "text": r["text"]}
            )
    except Exception:
        pass

    # 3. Reciprocal Rank Fusion: score = sum(1 / (60 + rank)) across both lists
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
