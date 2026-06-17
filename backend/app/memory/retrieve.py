import json
from typing import List, Dict, Any, Optional
from app.memory.embed import embed
from app.memory.index import get_db_connection

async def retrieve(
    query: str,
    active_conv_id: Optional[str] = None,
    top_k: int = 3
) -> List[Dict[str, Any]]:
    """
    Retrieves the top_k most relevant past memory chunks using hybrid search (vector + FTS5)
    and combines them using Reciprocal Rank Fusion (RRF).
    """
    # 1. Generate query embedding
    try:
        query_vector = await embed(query)
    except Exception as e:
        # If embedding fails (e.g. API down and no Ollama), fallback gracefully to keyword search only
        query_vector = None
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    vec_results = []
    fts_results = []
    
    candidate_k = max(20, top_k * 4)
    
    # 2. Vector Search Candidates
    if query_vector:
        try:
            # Query nearest candidates from vec0 table
            cursor.execute(
                """
                SELECT c.rowid, c.conv_id, c.text
                FROM vec_chunks v
                JOIN chunks c ON v.rowid = c.rowid
                WHERE v.embedding MATCH ? AND v.k = ?
                """,
                (json.dumps(query_vector), candidate_k)
            )
            rows = cursor.fetchall()
            for r in rows:
                if active_conv_id and r["conv_id"] == active_conv_id:
                    continue
                vec_results.append({
                    "rowid": r["rowid"],
                    "conv_id": r["conv_id"],
                    "text": r["text"]
                })
        except Exception:
            # Handle potential db or vec extension issues gracefully
            pass
            
    # 3. FTS5 Keyword Search Candidates
    try:
        # Split search terms for standard query, fallback to exact query
        search_terms = " OR ".join([f'"{term}"' for term in query.split() if term])
        if not search_terms:
            search_terms = query
            
        cursor.execute(
            """
            SELECT c.rowid, c.conv_id, c.text
            FROM chunks_fts f
            JOIN chunks c ON f.rowid = c.rowid
            WHERE chunks_fts MATCH ?
            LIMIT ?
            """,
            (search_terms, candidate_k)
        )
        rows = cursor.fetchall()
        for r in rows:
            if active_conv_id and r["conv_id"] == active_conv_id:
                continue
            fts_results.append({
                "rowid": r["rowid"],
                "conv_id": r["conv_id"],
                "text": r["text"]
            })
    except Exception:
        pass
        
    conn.close()
    
    # 4. Reciprocal Rank Fusion (RRF)
    # score = 1.0 / (60 + rank_vec) + 1.0 / (60 + rank_fts)
    scores: Dict[int, float] = {}
    docs_map: Dict[int, Dict[str, Any]] = {}
    
    for rank, doc in enumerate(vec_results, start=1):
        rowid = doc["rowid"]
        scores[rowid] = scores.get(rowid, 0.0) + (1.0 / (60.0 + rank))
        docs_map[rowid] = doc
        
    for rank, doc in enumerate(fts_results, start=1):
        rowid = doc["rowid"]
        scores[rowid] = scores.get(rowid, 0.0) + (1.0 / (60.0 + rank))
        docs_map[rowid] = doc
        
    # Sort docs by final RRF score descending
    sorted_rowids = sorted(scores.keys(), key=lambda r: scores[r], reverse=True)
    
    results = [docs_map[r] for r in sorted_rowids[:top_k]]
    return results
