"""Postgres client (replaces the Supabase client).

Self-hosted Postgres, connected to directly with psycopg3 (sync — every
caller here is already a blocking function invoked via run_in_threadpool,
mirroring how the Supabase client was also sync). No connection pool: this is
a low-traffic single/few-user app and a fresh connection per call is simpler
and cheap on a local Docker network; the old REST-over-HTTPS round-trip to
Supabase's cloud already paid a larger, per-call connection cost than this.

Usage:
    from app.db.postgres_client import fetchone, fetchall, execute
    row = fetchone("select * from users where user_id = %s", (user_id,))
"""

from contextlib import contextmanager
from typing import Any, Optional, Sequence

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from app.config import POSTGRES_DSN


def _connect() -> psycopg.Connection:
    if not POSTGRES_DSN:
        raise RuntimeError("POSTGRES_DSN must be configured")
    conn = psycopg.connect(POSTGRES_DSN, row_factory=dict_row)
    # Lets a Python list be passed straight as a `vector(N)` column/param
    # (memory_chunks.embedding, match_memory_chunks' query_embedding).
    register_vector(conn)
    return conn


def fetchone(sql: str, params: Sequence[Any] = ()) -> Optional[dict]:
    """Run a query and return the first row as a dict, or None."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()


def fetchall(sql: str, params: Sequence[Any] = ()) -> list[dict]:
    """Run a query and return all rows as dicts."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def execute(sql: str, params: Sequence[Any] = ()) -> None:
    """Run a statement with no result rows needed (or where the caller
    doesn't care about the RETURNING clause, if any)."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)


class TxHandle:
    """fetchone/fetchall/execute bound to one connection, for use inside a
    `transaction()` block — same shape as the module-level functions."""

    def __init__(self, conn: psycopg.Connection):
        self._conn = conn

    def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Optional[dict]:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)


@contextmanager
def transaction():
    """Run multiple statements atomically on one connection (single BEGIN/COMMIT,
    rolled back together on exception) — for read-then-write sequences that must
    not interleave with a concurrent request (e.g. check-then-insert).

    Usage:
        with transaction() as tx:
            tx.execute("update ... where ...", (...))
            row = tx.fetchone("insert into ... returning id", (...))
    """
    with _connect() as conn:
        yield TxHandle(conn)
