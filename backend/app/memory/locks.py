"""Per-(user, conv) asyncio lock (Phase M — memory scoping, M.5).

Shared by M.3's index_turn_task and M.5's project chat moves: a turn being
indexed mid-move must either finish under the old scope before the move
proceeds, or index under the new scope after it -- never interleave. See
workspace/plan/plan_memory_scoping.md §5 M.5.

Module-level dict, keyed per process (mirrors routes/generate.py's existing
per-(user,model) lock pattern) -- fine at this app's single/few-user scale;
entries are never evicted, which is an accepted, bounded cost (one Lock
object per distinct conv_id ever seen).
"""

import asyncio

_locks: dict[tuple[str, str], asyncio.Lock] = {}


def get_conv_lock(user_id: str, conv_id: str) -> asyncio.Lock:
    key = (user_id, conv_id)
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock
