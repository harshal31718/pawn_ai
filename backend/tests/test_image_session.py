"""Tests for Phase W.0 — warm/persistent Kaggle image sessions (CPU echo POC).

Postgres (`fetchone`/`fetchall`/`execute`) and Kaggle (`deploy_kernel`) are
mocked — no real external calls (testing rule). These cover the session
manager and the session/job routes that prove the persistent-loop rendezvous.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app.core import image_session
from app.main import app


def _iso(dt):
    return dt.isoformat()


class _FakeDB:
    """Routes fetchone/fetchall/execute calls to per-table row lists based on
    simple substring sniffing of the SQL text — enough for these tests' shapes.
    INSERTs return a fixed `{table}-id-1` id, mirroring the old Supabase-mock
    fixture's ids so existing assertions don't need to change."""

    def __init__(self, rows=None):
        self.rows = {k: list(v) for k, v in (rows or {}).items()}
        self.calls = []  # (kind, sql, params)

    def _table(self, sql):
        if "image_sessions" in sql:
            return "image_sessions"
        if "image_jobs" in sql:
            return "image_jobs"
        return None

    def fetchone(self, sql, params=()):
        self.calls.append(("fetchone", sql, params))
        table = self._table(sql)
        if sql.strip().lower().startswith("insert into"):
            return {"id": f"{table}-id-1"}
        rows = self.rows.get(table, [])
        return rows[0] if rows else None

    def fetchall(self, sql, params=()):
        self.calls.append(("fetchall", sql, params))
        table = self._table(sql)
        return list(self.rows.get(table, []))

    def execute(self, sql, params=()):
        self.calls.append(("execute", sql, params))

    @contextmanager
    def tx(self):
        """Fake for postgres_client.transaction() — same fetchone/fetchall/execute
        shape, routed through this same fake DB (no real transaction semantics
        needed for these tests)."""
        yield self


def _patch_db(db):
    """Patch all postgres_client functions used by image_session.py onto one
    fake so a single fixture works for every call shape in a test."""
    return (
        patch("app.core.image_session.fetchone", side_effect=db.fetchone),
        patch("app.core.image_session.fetchall", side_effect=db.fetchall),
        patch("app.core.image_session.execute", side_effect=db.execute),
        patch("app.core.image_session.transaction", db.tx),
    )


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# --- Session manager ---------------------------------------------------------


def test_start_session_sdxl_uses_gpu_serve_loop():
    """SDXL warm sessions push the real GPU serve-loop (load once → generate images),
    not the old CPU echo POC."""
    from app.core.image_models import IMAGE_MODELS

    db = _FakeDB()
    captured = {}

    def fake_deploy(**kwargs):
        captured.update(kwargs)

    cfg = {"username": "alice", "api_token": "tok"}
    p1, p2, p3, p4 = _patch_db(db)
    with patch("app.core.image_session.key_store.get_kaggle", return_value=cfg), \
         p1, p2, p3, p4, \
         patch("app.core.image_session.config.POSTGREST_PUBLIC_URL", "https://pawnai.duckdns.org/rest"), \
         patch("app.core.image_session.kaggle.deploy_kernel", side_effect=fake_deploy):
        out = image_session.start_session("user-1", "sdxl", 60, None)

    sdxl = IMAGE_MODELS["sdxl"]
    assert out["session_id"] == "image_sessions-id-1"
    assert out["status"] == "starting"
    assert captured["enable_gpu"] is True
    assert captured["enable_internet"] is True
    assert captured["dataset_sources"] == [sdxl.dataset]
    assert captured["accelerator"] == sdxl.accelerator
    assert captured["kernel_name"] == sdxl.session_slug == "pawn-sdxl-session"


def test_start_session_injects_postgrest_url_never_dsn():
    """Security: only the public PostgREST URL is injected — never the
    backend's own Postgres DSN (which can reach every table)."""
    db = _FakeDB()
    captured = {}

    def fake_deploy(**kwargs):
        captured.update(kwargs)

    cfg = {"username": "alice", "api_token": "tok"}
    p1, p2, p3, p4 = _patch_db(db)
    with patch("app.core.image_session.key_store.get_kaggle", return_value=cfg), \
         p1, p2, p3, p4, \
         patch("app.core.image_session.config.POSTGREST_PUBLIC_URL", "https://pawnai.duckdns.org/rest"), \
         patch("app.core.image_session.config.POSTGRES_DSN", "postgresql://pawn:supersecret@postgres:5432/pawn"), \
         patch("app.core.image_session.kaggle.deploy_kernel", side_effect=fake_deploy):
        image_session.start_session("user-1", "sdxl", 60, None)

    import base64
    import json
    import re

    src = captured["source"]
    # Payload is base64-injected, not interpolated as raw source. The notebook is
    # .ipynb JSON, so the quotes around the token are backslash-escaped.
    assert "__PAWN_PAYLOAD_B64__" not in src
    m = re.search(r'b64decode\(\\?"([A-Za-z0-9+/=]+)\\?"', src)
    assert m, "injected base64 payload not found in kernel source"
    payload = json.loads(base64.b64decode(m.group(1)).decode())
    assert payload["postgrest_url"] == "https://pawnai.duckdns.org/rest"
    # The backend's own DSN/password must never reach the notebook (security).
    assert "supersecret" not in src
    assert "supersecret" not in json.dumps(payload)


def test_start_session_flux_uses_gpu_and_dataset():
    """The FLUX warm session pushes the serve-loop notebook with the GPU + dataset."""
    from app.core.image_models import IMAGE_MODELS

    db = _FakeDB()
    captured = {}

    def fake_deploy(**kwargs):
        captured.update(kwargs)

    cfg = {"username": "alice", "api_token": "tok"}
    p1, p2, p3, p4 = _patch_db(db)
    with patch("app.core.image_session.key_store.get_kaggle", return_value=cfg), \
         p1, p2, p3, p4, \
         patch("app.core.image_session.config.POSTGREST_PUBLIC_URL", "https://pawnai.duckdns.org/rest"), \
         patch("app.core.image_session.kaggle.deploy_kernel", side_effect=fake_deploy):
        image_session.start_session("user-1", "flux", 60, None)

    flux = IMAGE_MODELS["flux"]
    assert captured["kernel_name"] == flux.session_slug == "pawn-flux-session"
    assert captured["enable_gpu"] is True
    assert captured["dataset_sources"] == [flux.dataset]
    assert captured["accelerator"] == flux.accelerator


def test_session_slug_titles_round_trip():
    """Kaggle derives a notebook slug from its title; every model's session_slug
    must slugify back to itself or the session push 409s (same invariant as the
    cold slugs in test_generate.py)."""
    from app.core.image_models import IMAGE_MODELS

    for spec in IMAGE_MODELS.values():
        if not spec.session_slug:
            continue
        title = image_session._session_title(spec.session_slug)
        assert title.lower().replace(" ", "-") == spec.session_slug, spec.id


def test_extend_session_bumps_expiry_capped():
    from app.constants import IMAGE_SESSION_MAX_DURATION_MINUTES

    now = datetime.now(timezone.utc)
    sess = {
        "id": "s1",
        "user_id": "user-1",
        "status": "ready",
        "heartbeat_at": _iso(now),
        "expires_at": _iso(now + timedelta(minutes=10)),
    }
    db = _FakeDB(rows={"image_sessions": [sess]})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4:
        out = image_session.extend_session("user-1", "s1", 30)
    new_exp = image_session._parse_ts(out["expires_at"])
    assert new_exp > now + timedelta(minutes=35)  # bumped from +10 by +30
    cap = now + timedelta(minutes=IMAGE_SESSION_MAX_DURATION_MINUTES)
    assert new_exp <= cap + timedelta(seconds=5)


def test_extend_session_dead_session_raises():
    from app.exceptions import NotConfiguredError

    dead = {"id": "s1", "user_id": "user-1", "status": "ended"}
    db = _FakeDB(rows={"image_sessions": [dead]})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4:
        with pytest.raises(NotConfiguredError):
            image_session.extend_session("user-1", "s1", 30)


def test_start_session_unknown_model_raises():
    from app.exceptions import UnknownModelError

    cfg = {"username": "alice", "api_token": "tok"}
    with patch("app.core.image_session.key_store.get_kaggle", return_value=cfg):
        with pytest.raises(UnknownModelError):
            image_session.start_session("user-1", "does-not-exist")


def test_start_session_not_configured():
    from app.exceptions import NotConfiguredError

    with patch("app.core.image_session.key_store.get_kaggle", return_value=None):
        with pytest.raises(NotConfiguredError):
            image_session.start_session("user-1", "sdxl")


def test_start_session_caps_duration():
    """A duration past the backstop is clamped to IMAGE_SESSION_MAX_DURATION_MINUTES."""
    from app.constants import IMAGE_SESSION_MAX_DURATION_MINUTES

    db = _FakeDB()
    cfg = {"username": "alice", "api_token": "tok"}
    p1, p2, p3, p4 = _patch_db(db)
    with patch("app.core.image_session.key_store.get_kaggle", return_value=cfg), \
         p1, p2, p3, p4, \
         patch("app.core.image_session.config.POSTGREST_PUBLIC_URL", "https://pawnai.duckdns.org/rest"), \
         patch("app.core.image_session.kaggle.deploy_kernel"):
        out = image_session.start_session("user-1", "sdxl", 9999, None)

    expires = image_session._parse_ts(out["expires_at"])
    cap = datetime.now(timezone.utc) + timedelta(minutes=IMAGE_SESSION_MAX_DURATION_MINUTES)
    assert expires <= cap + timedelta(seconds=5)


def test_submit_session_job_inserts_queued_row():
    now = datetime.now(timezone.utc)
    live = {
        "id": "s1",
        "user_id": "user-1",
        "model": "flux",
        "status": "ready",
        "expires_at": _iso(now + timedelta(minutes=30)),
        "heartbeat_at": _iso(now),
    }
    db = _FakeDB(rows={"image_sessions": [live]})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4:
        job_id = image_session.submit_session_job("user-1", "s1", "a red apple")

    assert job_id == "image_jobs-id-1"
    insert_call = next(
        c for c in db.calls if c[0] == "fetchone" and "insert into image_jobs" in c[1]
    )
    params = insert_call[2]
    assert params[0] == "user-1"
    assert params[1] == "s1"
    assert params[2] == "flux"
    assert params[3] == "a red apple"


def test_submit_session_job_missing_session_raises():
    from app.exceptions import NotConfiguredError

    db = _FakeDB(rows={"image_sessions": []})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4:
        with pytest.raises(NotConfiguredError):
            image_session.submit_session_job("user-1", "gone", "x")


def test_submit_session_job_dead_session_raises():
    """A job for a stopped/ended session is rejected, not silently queued forever."""
    from app.exceptions import NotConfiguredError

    dead = {"id": "s1", "user_id": "user-1", "model": "flux", "status": "ended"}
    db = _FakeDB(rows={"image_sessions": [dead]})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4:
        with pytest.raises(NotConfiguredError):
            image_session.submit_session_job("user-1", "s1", "x")


def test_start_session_missing_postgrest_config_raises():
    """Without a public PostgREST URL the kernel can't rendezvous → fail early."""
    from app.exceptions import NotConfiguredError

    cfg = {"username": "alice", "api_token": "tok"}
    with patch("app.core.image_session.key_store.get_kaggle", return_value=cfg), \
         patch("app.core.image_session.config.POSTGREST_PUBLIC_URL", ""):
        with pytest.raises(NotConfiguredError):
            image_session.start_session("user-1", "sdxl")


def test_get_job_returns_result_once_done():
    row = {
        "id": "j1",
        "status": "done",
        "model": "sdxl",
        "prompt": "hi",
        "image_b64": "RUNITz==",
        "mime": "text/plain",
        "via": "kaggle:session-poc",
        "error": None,
        "created_at": "2026-06-29T00:00:00+00:00",
    }
    db = _FakeDB(rows={"image_jobs": [row]})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4:
        out = image_session.get_job("user-1", "j1")

    assert out["job_id"] == "j1"
    assert out["status"] == "done"
    assert out["image_b64"] == "RUNITz=="


def test_get_job_missing_returns_none():
    db = _FakeDB(rows={"image_jobs": []})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4:
        assert image_session.get_job("user-1", "nope") is None


def test_get_session_status_none_when_absent():
    db = _FakeDB(rows={"image_sessions": []})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4:
        out = image_session.get_session_status("user-1", "sdxl")
    assert out == {"status": "none", "alive": False}


def test_get_session_status_fresh_ready_is_alive():
    now = datetime.now(timezone.utc)
    row = {
        "id": "s1",
        "status": "ready",
        "expires_at": _iso(now + timedelta(minutes=30)),
        "heartbeat_at": _iso(now),
        "images_done": 2,
        "max_images": 10,
    }
    db = _FakeDB(rows={"image_sessions": [row]})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4:
        out = image_session.get_session_status("user-1", "sdxl")
    assert out["alive"] is True
    assert out["images_done"] == 2


def test_get_session_status_stale_heartbeat_not_alive():
    now = datetime.now(timezone.utc)
    row = {
        "id": "s1",
        "status": "ready",
        "expires_at": _iso(now + timedelta(minutes=30)),
        "heartbeat_at": _iso(now - timedelta(minutes=5)),  # stale
        "images_done": 0,
    }
    db = _FakeDB(rows={"image_sessions": [row]})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4:
        out = image_session.get_session_status("user-1", "sdxl")
    assert out["alive"] is False


def test_get_session_status_expired_not_alive():
    now = datetime.now(timezone.utc)
    row = {
        "id": "s1",
        "status": "ready",
        "expires_at": _iso(now - timedelta(minutes=1)),  # already expired
        "heartbeat_at": _iso(now),
        "images_done": 0,
    }
    db = _FakeDB(rows={"image_sessions": [row]})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4:
        out = image_session.get_session_status("user-1", "sdxl")
    assert out["alive"] is False


def test_stop_session_sets_stopping():
    db = _FakeDB()
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4:
        image_session.stop_session("user-1", "s1")
    assert any(
        kind == "execute" and "'stopping'" in sql and params == ("s1", "user-1")
        for kind, sql, params in db.calls
    )


# --- Routes ------------------------------------------------------------------


def test_route_session_start(client):
    out = {"session_id": "s1", "expires_at": "2026-06-29T01:00:00+00:00", "status": "starting"}
    with patch("app.routes.generate.image_session.start_session", return_value=out) as m:
        resp = client.post(
            "/generate/session/start",
            json={"model": "flux", "duration_minutes": 60, "max_images": 10},
        )
    assert resp.status_code == 200
    assert resp.json()["session_id"] == "s1"
    m.assert_called_once_with("test-user-id", "flux", 60, 10)


def test_route_session_status(client):
    out = {"status": "ready", "alive": True, "session_id": "s1", "images_done": 1}
    with patch("app.routes.generate.image_session.get_session_status", return_value=out) as m:
        resp = client.get("/generate/session/status", params={"model": "sdxl"})
    assert resp.status_code == 200
    assert resp.json()["alive"] is True
    m.assert_called_once_with("test-user-id", "sdxl")


def test_route_session_job(client):
    with patch("app.routes.generate.image_session.submit_session_job", return_value="j1") as m:
        resp = client.post(
            "/generate/session/job", json={"session_id": "s1", "prompt": "a cat"}
        )
    assert resp.status_code == 200
    assert resp.json() == {"job_id": "j1", "status": "queued"}
    args = m.call_args.args
    assert args[:3] == ("test-user-id", "s1", "a cat")


def test_route_session_job_requires_prompt(client):
    resp = client.post("/generate/session/job", json={"session_id": "s1", "prompt": "   "})
    assert resp.status_code == 400


def test_route_session_stop(client):
    with patch("app.routes.generate.image_session.stop_session") as m:
        resp = client.post("/generate/session/stop", json={"session_id": "s1"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    m.assert_called_once_with("test-user-id", "s1")


def test_route_session_extend(client):
    out = {"session_id": "s1", "expires_at": "2026-06-29T02:00:00+00:00"}
    with patch("app.routes.generate.image_session.extend_session", return_value=out) as m:
        resp = client.post(
            "/generate/session/extend", json={"session_id": "s1", "add_minutes": 30}
        )
    assert resp.status_code == 200
    assert resp.json()["expires_at"].endswith("02:00:00+00:00")
    m.assert_called_once_with("test-user-id", "s1", 30)


def test_route_get_job(client):
    job = {"job_id": "j1", "status": "done", "image_b64": "x", "mime": "text/plain"}
    with patch("app.routes.generate.image_session.get_job", return_value=job) as m:
        resp = client.get("/generate/job/j1")
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"
    m.assert_called_once_with("test-user-id", "j1")


def test_route_get_job_404(client):
    with patch("app.routes.generate.image_session.get_job", return_value=None):
        resp = client.get("/generate/job/missing")
    assert resp.status_code == 404
