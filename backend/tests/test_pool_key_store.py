"""PAWN 2.0 Phase B.3: pool_key_store -- operator-owned shared pool key
storage, encrypted, admin-editable live via a short-TTL cache with explicit
eviction on every write (not a long-lived @lru_cache, unlike Phase 1b's old
config.read_pool_key -- see test_pool_keys.py's B.4 coverage for that)."""

from unittest.mock import patch

from app.core import pool_key_store


def _reset_cache():
    with pool_key_store._POOL_LOCK:
        pool_key_store._POOL_CACHE.clear()


def test_set_pool_key_encrypts_and_upserts():
    _reset_cache()
    with patch("app.core.pool_key_store.encrypt", return_value="ENC(secret)") as enc, \
         patch("app.core.pool_key_store.execute") as exec_mock:
        pool_key_store.set_pool_key("groq", "secret")
    enc.assert_called_once_with("secret")
    args, kwargs = exec_mock.call_args
    assert "groq" in args[1]
    assert "ENC(secret)" in args[1]


def test_get_pool_key_decrypts_when_enabled():
    _reset_cache()
    row = {"provider": "groq", "key_enc": "ENC(secret)", "enabled": True, "saturation_pct": None}
    with patch("app.core.pool_key_store.fetchone", return_value=row), \
         patch("app.core.pool_key_store.decrypt", return_value="secret"):
        assert pool_key_store.get_pool_key("groq") == "secret"


def test_get_pool_key_none_when_disabled():
    _reset_cache()
    row = {"provider": "groq", "key_enc": "ENC(secret)", "enabled": False, "saturation_pct": None}
    with patch("app.core.pool_key_store.fetchone", return_value=row):
        assert pool_key_store.get_pool_key("groq") is None


def test_get_pool_key_none_when_no_row():
    _reset_cache()
    with patch("app.core.pool_key_store.fetchone", return_value=None):
        assert pool_key_store.get_pool_key("groq") is None


def test_get_pool_config_caches_result():
    _reset_cache()
    row = {"provider": "groq", "key_enc": "ENC(x)", "enabled": True, "saturation_pct": None}
    with patch("app.core.pool_key_store.fetchone", return_value=row) as fetch_mock:
        pool_key_store.get_pool_config("groq")
        pool_key_store.get_pool_config("groq")
    fetch_mock.assert_called_once()


def test_set_enabled_evicts_cache():
    _reset_cache()
    with pool_key_store._POOL_LOCK:
        pool_key_store._POOL_CACHE["groq"] = (1e18, {"enabled": True})
    with patch("app.core.pool_key_store.execute"):
        pool_key_store.set_enabled("groq", False)
    with pool_key_store._POOL_LOCK:
        assert "groq" not in pool_key_store._POOL_CACHE


def test_delete_pool_key_evicts_cache():
    _reset_cache()
    with pool_key_store._POOL_LOCK:
        pool_key_store._POOL_CACHE["groq"] = (1e18, {"enabled": True})
    with patch("app.core.pool_key_store.execute"):
        pool_key_store.delete_pool_key("groq")
    with pool_key_store._POOL_LOCK:
        assert "groq" not in pool_key_store._POOL_CACHE


def test_list_pool_providers_returns_rows():
    _reset_cache()
    rows = [{"provider": "groq", "enabled": True, "saturation_pct": None, "updated_at": None}]
    with patch("app.core.pool_key_store.fetchall", return_value=rows):
        assert pool_key_store.list_pool_providers() == rows


def test_list_pool_providers_empty_on_db_error():
    _reset_cache()
    with patch("app.core.pool_key_store.fetchall", side_effect=Exception("db down")):
        assert pool_key_store.list_pool_providers() == []
