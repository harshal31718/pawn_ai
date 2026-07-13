"""Turn indexing + scope resolution (Phase M — memory scoping, M.3).

Drive's per-chat rag_chunks.jsonl is the source of truth; Postgres
memory_chunks is a derived, rebuildable queryable index. Write order is
load-bearing: Drive first, Postgres second — a Drive failure aborts before
any Postgres write (no orphan index rows), while a Postgres failure after a
successful Drive write is recoverable via rebuild_index(). See
workspace/plan/plan_memory_scoping.md §5 M.3.
"""

import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from starlette.concurrency import run_in_threadpool

from app.constants import SCOPE_CACHE_TTL_SECONDS
from app.core.drive_factory import call_drive, require_drive_for_user
from app.exceptions import NotConfiguredError
from app.memory.chunker import chunk_turn
from app.storage import conversations_drive, projects_drive
from app.storage.drive import DriveStorage

Scope = Tuple[str, str]  # (scope_type, scope_id)

# In-process cache: (user_id, conv_id) -> (resolved_at, scope). Explicitly
# evicted on a chat move (M.5) so a moved chat's next turn indexes under its
# new scope instead of a stale cached one.
_SCOPE_CACHE: Dict[Tuple[str, str], Tuple[float, Scope]] = {}
_SCOPE_CACHE_LOCK = threading.Lock()


def evict_scope(user_id: str, conv_id: str) -> None:
    """Drop a cached scope resolution for one chat (call after moving it)."""
    with _SCOPE_CACHE_LOCK:
        _SCOPE_CACHE.pop((user_id, conv_id), None)


def resolve_scope(
    user_id: str, conv_id: str, drive: Optional[DriveStorage] = None
) -> Optional[Scope]:
    """Blocking. Return (scope_type, scope_id) for a chat: ('chat', conv_id)
    if standalone, ('project', project_id) if inside a project. Served from
    an in-process cache (SCOPE_CACHE_TTL_SECONDS) on a hit; on a miss, walks
    Drive folder placement (conversations_drive.resolve_conv_scope) and
    caches the result. Returns None if the chat doesn't exist anywhere.

    `drive` may be passed to reuse an already-resolved DriveStorage; otherwise
    one is fetched for `user_id` (raises NotConfiguredError if unavailable)."""
    key = (user_id, conv_id)
    now = time.time()
    with _SCOPE_CACHE_LOCK:
        entry = _SCOPE_CACHE.get(key)
        if entry is not None and now - entry[0] < SCOPE_CACHE_TTL_SECONDS:
            return entry[1]

    if drive is None:
        drive = require_drive_for_user(user_id)
    scope = call_drive(conversations_drive.resolve_conv_scope, drive, conv_id)
    if scope is not None:
        with _SCOPE_CACHE_LOCK:
            _SCOPE_CACHE[key] = (now, scope)
    return scope


def _write_chunks_to_drive(
    drive: DriveStorage, conv_id: str, chunks: List[Dict[str, Any]]
) -> None:
    """Blocking: stamp conv_id onto each chunk and append to the chat's own
    rag_chunks.jsonl. Must succeed before any Postgres write is attempted."""
    records = [{**c, "conv_id": conv_id} for c in chunks]
    conversations_drive.append_rag_chunks(drive, conv_id, records)


async def _embed_and_index(
    user_id: str,
    conv_id: str,
    scope_type: str,
    scope_id: str,
    chunks: List[Dict[str, Any]],
) -> None:
    """Embed each chunk and upsert it into Postgres. Best-effort per chunk —
    a failure here is recoverable via rebuild_index() since Drive already has
    the chunk text as of _write_chunks_to_drive."""
    from app.memory.embed import embed
    from app.memory.index import add_chunk

    for chunk in chunks:
        try:
            embedding = await embed(chunk["text"], user_id=user_id)
        except Exception as e:
            print(
                f"Failed to embed chunk {chunk.get('chunk_id')} for {conv_id}: {e}",
                file=sys.stderr,
            )
            continue
        await run_in_threadpool(
            add_chunk,
            user_id,
            scope_type,
            scope_id,
            conv_id,
            chunk["chunk_id"],
            chunk.get("msg_index"),
            chunk["text"],
            embedding,
        )


async def index_turn_task(
    user_id: Optional[str],
    conv_id: Optional[str],
    scope: Optional[Scope],
    turn_msgs: List[Dict[str, Any]],
) -> None:
    """Background task scheduled from chat.py's persist-turn block. Chunks a
    committed turn, appends the chunks to the chat's own rag_chunks.jsonl on
    Drive, then embeds and writes scoped rows into Postgres.

    Stateless chats (conv_id is None/falsy) are never indexed — no
    conversation, no memory, matching their existing no-persistence
    semantics. `scope` may be a precomputed (scope_type, scope_id) tuple;
    pass None to resolve it fresh (e.g. from folder placement) inside this
    task, which is always safe since scope can change between scheduling and
    execution (a move mid-flight)."""
    if not user_id or not conv_id or not turn_msgs:
        return

    try:
        drive = await run_in_threadpool(require_drive_for_user, user_id)
    except NotConfiguredError:
        return

    if scope is None:
        try:
            scope = await run_in_threadpool(resolve_scope, user_id, conv_id, drive)
        except NotConfiguredError:
            return
    if scope is None:
        return
    scope_type, scope_id = scope

    # Accepted race (documented, not fixed here): this re-reads history rather
    # than taking the message count chat.py already had post-persist, because
    # the plan locks index_turn_task's signature to exactly (user_id, conv_id,
    # scope, turn_msgs). Two turns on the same chat indexing concurrently could
    # each see a snapshot that includes the other's messages, mis-attributing
    # msg_index on their chunks. Blast radius is provenance/display metadata
    # only -- it never affects which scope a chunk lands in or retrieval
    # correctness (see plan_memory_scoping.md M.3; code-reviewer WARN, 2026-07-13).
    history = await run_in_threadpool(call_drive, conversations_drive.load_messages, drive, conv_id)
    msg_index_start = max(len(history) - len(turn_msgs), 0)
    chunks = chunk_turn(turn_msgs, msg_index_start=msg_index_start)
    if not chunks:
        return

    try:
        await run_in_threadpool(call_drive, _write_chunks_to_drive, drive, conv_id, chunks)
    except NotConfiguredError as e:
        print(f"Failed to write rag_chunks for {conv_id}: {e}", file=sys.stderr)
        return

    await _embed_and_index(user_id, conv_id, scope_type, scope_id, chunks)


async def rebuild_index(user_id: str, scope_type: str, scope_id: str) -> int:
    """Delete this scope's Postgres rows, then re-read + re-embed every
    relevant chat's rag_chunks.jsonl from Drive and re-insert. Drive layout is
    always authoritative; Postgres is always regenerable from it. Returns the
    number of chunks re-indexed."""
    from app.db.postgres_client import execute
    from app.memory.embed import embed
    from app.memory.index import add_chunk

    drive = await run_in_threadpool(require_drive_for_user, user_id)

    if scope_type == "chat":
        conv_ids = [scope_id]
    else:
        chat_metas = await run_in_threadpool(
            call_drive, projects_drive.list_project_chats, drive, scope_id
        )
        conv_ids = [m["id"] for m in chat_metas]

    await run_in_threadpool(
        execute,
        "delete from memory_chunks where user_id = %s and scope_type = %s and scope_id = %s",
        (user_id, scope_type, scope_id),
    )

    total = 0
    for conv_id in conv_ids:
        chunks = await run_in_threadpool(call_drive, conversations_drive.load_rag_chunks, drive, conv_id)
        for chunk in chunks:
            try:
                embedding = await embed(chunk["text"], user_id=user_id)
            except Exception as e:
                print(
                    f"Failed to re-embed chunk {chunk.get('chunk_id')} for {conv_id}: {e}",
                    file=sys.stderr,
                )
                continue
            await run_in_threadpool(
                add_chunk,
                user_id,
                scope_type,
                scope_id,
                conv_id,
                chunk["chunk_id"],
                chunk.get("msg_index"),
                chunk["text"],
                embedding,
            )
            total += 1
    return total
