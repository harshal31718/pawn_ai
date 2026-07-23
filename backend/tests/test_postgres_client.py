"""PAWN 2.0 Phase E.4: postgres_client's optional `dsn` override, the
mechanism key_store.py / pool_key_store.py use to route the shared-keys
tables at SHARED_DB_DSN instead of the per-environment POSTGRES_DSN every
other table uses. No dsn passed -> today's exact behavior (POSTGRES_DSN)."""

from unittest.mock import MagicMock, patch

from app.db import postgres_client


def _fake_conn():
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cur
    return conn, cur


def test_connect_uses_postgres_dsn_by_default():
    with patch("app.db.postgres_client.POSTGRES_DSN", "postgresql://a/db"), \
         patch("app.db.postgres_client.psycopg.connect") as connect_mock, \
         patch("app.db.postgres_client.register_vector"):
        postgres_client._connect()
    connect_mock.assert_called_once_with("postgresql://a/db", row_factory=postgres_client.dict_row)


def test_connect_uses_explicit_dsn_override_when_given():
    with patch("app.db.postgres_client.POSTGRES_DSN", "postgresql://a/db"), \
         patch("app.db.postgres_client.psycopg.connect") as connect_mock, \
         patch("app.db.postgres_client.register_vector"):
        postgres_client._connect(dsn="postgresql://shared/db")
    connect_mock.assert_called_once_with("postgresql://shared/db", row_factory=postgres_client.dict_row)


def test_connect_raises_when_no_dsn_resolves():
    with patch("app.db.postgres_client.POSTGRES_DSN", None):
        try:
            postgres_client._connect()
            assert False, "expected RuntimeError"
        except RuntimeError:
            pass


def test_fetchone_passes_dsn_through_to_connect():
    conn, cur = _fake_conn()
    cur.fetchone.return_value = {"id": 1}
    with patch("app.db.postgres_client._connect", return_value=conn) as connect_mock:
        result = postgres_client.fetchone("select 1", dsn="postgresql://shared/db")
    connect_mock.assert_called_once_with("postgresql://shared/db")
    assert result == {"id": 1}


def test_execute_passes_dsn_through_to_connect():
    conn, cur = _fake_conn()
    with patch("app.db.postgres_client._connect", return_value=conn) as connect_mock:
        postgres_client.execute("insert into x values (1)", dsn="postgresql://shared/db")
    connect_mock.assert_called_once_with("postgresql://shared/db")
