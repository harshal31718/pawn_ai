"""Tests for Phase W.0 — warm/persistent Kaggle image sessions (CPU echo POC).

Supabase (`get_db`) and Kaggle (`deploy_kernel`) are mocked — no real external
calls (testing rule). These cover the session manager and the session/job routes
that prove the persistent-loop rendezvous.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app.core import image_session
from app.main import app


def _iso(dt):
    return dt.isoformat()


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Minimal chainable stand-in for a supabase-py table query.

    Records the operation + filters/values and returns rows the FakeDB is seeded
    with. Every chain method returns self; execute() returns the recorded result.
    """

    def __init__(self, db, table):
        self._db = db
        self._table = table
        self._op = "select"
        self._values = None

    def insert(self, values):
        self._op = "insert"
        self._values = values
        return self

    def update(self, values):
        self._op = "update"
        self._values = values
        return self

    def select(self, *_a, **_k):
        self._op = "select"
        return self

    def eq(self, *_a, **_k):
        return self

    def in_(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        self._db.calls.append((self._table, self._op, self._values))
        if self._op == "insert":
            row = dict(self._values)
            row.setdefault("id", f"{self._table}-id-1")
            self._db.inserted.append((self._table, row))
            return _Result([row])
        if self._op == "update":
            return _Result([])
        return _Result(list(self._db.rows.get(self._table, [])))


class _FakeDB:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.calls = []
        self.inserted = []

    def table(self, name):
        return _Query(self, name)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# --- Session manager ---------------------------------------------------------


def test_start_session_inserts_row_and_pushes_cpu_notebook():
    db = _FakeDB()
    captured = {}

    def fake_deploy(**kwargs):
        captured.update(kwargs)

    cfg = {"username": "alice", "api_token": "tok"}
    with patch("app.core.image_session.key_store.get_kaggle", return_value=cfg), \
         patch("app.core.image_session.get_db", return_value=db), \
         patch("app.core.image_session.config.SUPABASE_URL", "https://proj.supabase.co"), \
         patch("app.core.image_session.config.SUPABASE_ANON_KEY", "anon-public-key"), \
         patch("app.core.image_session.config.SUPABASE_SERVICE_KEY", "service-secret-key"), \
         patch("app.core.image_session.kaggle.deploy_kernel", side_effect=fake_deploy):
        out = image_session.start_session("user-1", "sdxl", 60, None)

    assert out["session_id"] == "image_sessions-id-1"
    assert out["status"] == "starting"
    # Pushed as a CPU kernel (no GPU/dataset) for the echo POC.
    assert captured["enable_gpu"] is False
    assert captured["enable_internet"] is True
    assert captured["dataset_sources"] == []
    assert captured["kernel_name"] == "pawn-session-poc"


def test_start_session_injects_anon_key_never_service_key():
    """Security: only the PUBLIC anon key is injected — never the service key."""
    db = _FakeDB()
    captured = {}

    def fake_deploy(**kwargs):
        captured.update(kwargs)

    cfg = {"username": "alice", "api_token": "tok"}
    with patch("app.core.image_session.key_store.get_kaggle", return_value=cfg), \
         patch("app.core.image_session.get_db", return_value=db), \
         patch("app.core.image_session.config.SUPABASE_URL", "https://proj.supabase.co"), \
         patch("app.core.image_session.config.SUPABASE_ANON_KEY", "anon-public-key"), \
         patch("app.core.image_session.config.SUPABASE_SERVICE_KEY", "service-secret-key"), \
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
    assert payload["anon_key"] == "anon-public-key"
    # The master service key must never reach the notebook (security).
    assert "service-secret-key" not in src
    assert "service-secret-key" not in json.dumps(payload)


def test_start_session_flux_uses_gpu_and_dataset():
    """The FLUX warm session pushes the serve-loop notebook with the GPU + dataset."""
    from app.core.image_models import IMAGE_MODELS

    db = _FakeDB()
    captured = {}

    def fake_deploy(**kwargs):
        captured.update(kwargs)

    cfg = {"username": "alice", "api_token": "tok"}
    with patch("app.core.image_session.key_store.get_kaggle", return_value=cfg), \
         patch("app.core.image_session.get_db", return_value=db), \
         patch("app.core.image_session.config.SUPABASE_URL", "https://proj.supabase.co"), \
         patch("app.core.image_session.config.SUPABASE_ANON_KEY", "anon-public-key"), \
         patch("app.core.image_session.kaggle.deploy_kernel", side_effect=fake_deploy):
        image_session.start_session("user-1", "flux", 60, None)

    flux = IMAGE_MODELS["flux"]
    assert captured["kernel_name"] == flux.session_slug == "pawn-flux-session"
    assert captured["enable_gpu"] is True
    assert captured["dataset_sources"] == [flux.dataset]
    assert captured["accelerator"] == flux.accelerator


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
    with patch("app.core.image_session.get_db", return_value=db):
        out = image_session.extend_session("user-1", "s1", 30)
    new_exp = image_session._parse_ts(out["expires_at"])
    assert new_exp > now + timedelta(minutes=35)  # bumped from +10 by +30
    cap = now + timedelta(minutes=IMAGE_SESSION_MAX_DURATION_MINUTES)
    assert new_exp <= cap + timedelta(seconds=5)


def test_extend_session_dead_session_raises():
    from app.exceptions import NotConfiguredError

    dead = {"id": "s1", "user_id": "user-1", "status": "ended"}
    db = _FakeDB(rows={"image_sessions": [dead]})
    with patch("app.core.image_session.get_db", return_value=db):
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
    with patch("app.core.image_session.key_store.get_kaggle", return_value=cfg), \
         patch("app.core.image_session.get_db", return_value=db), \
         patch("app.core.image_session.config.SUPABASE_URL", "u"), \
         patch("app.core.image_session.config.SUPABASE_ANON_KEY", "k"), \
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
    with patch("app.core.image_session.get_db", return_value=db):
        job_id = image_session.submit_session_job("user-1", "s1", "a red apple")

    assert job_id == "image_jobs-id-1"
    table, row = db.inserted[-1]
    assert table == "image_jobs"
    assert row["status"] == "queued"
    assert row["session_id"] == "s1"
    assert row["model"] == "flux"
    assert row["prompt"] == "a red apple"


def test_submit_session_job_missing_session_raises():
    from app.exceptions import NotConfiguredError

    db = _FakeDB(rows={"image_sessions": []})
    with patch("app.core.image_session.get_db", return_value=db):
        with pytest.raises(NotConfiguredError):
            image_session.submit_session_job("user-1", "gone", "x")


def test_submit_session_job_dead_session_raises():
    """A job for a stopped/ended session is rejected, not silently queued forever."""
    from app.exceptions import NotConfiguredError

    dead = {"id": "s1", "user_id": "user-1", "model": "flux", "status": "ended"}
    db = _FakeDB(rows={"image_sessions": [dead]})
    with patch("app.core.image_session.get_db", return_value=db):
        with pytest.raises(NotConfiguredError):
            image_session.submit_session_job("user-1", "s1", "x")


def test_start_session_missing_supabase_config_raises():
    """Without a Supabase URL/anon key the kernel can't rendezvous → fail early."""
    from app.exceptions import NotConfiguredError

    cfg = {"username": "alice", "api_token": "tok"}
    with patch("app.core.image_session.key_store.get_kaggle", return_value=cfg), \
         patch("app.core.image_session.config.SUPABASE_URL", "https://proj.supabase.co"), \
         patch("app.core.image_session.config.SUPABASE_ANON_KEY", None):
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
    with patch("app.core.image_session.get_db", return_value=db):
        out = image_session.get_job("user-1", "j1")

    assert out["job_id"] == "j1"
    assert out["status"] == "done"
    assert out["image_b64"] == "RUNITz=="


def test_get_job_missing_returns_none():
    db = _FakeDB(rows={"image_jobs": []})
    with patch("app.core.image_session.get_db", return_value=db):
        assert image_session.get_job("user-1", "nope") is None


def test_get_session_status_none_when_absent():
    db = _FakeDB(rows={"image_sessions": []})
    with patch("app.core.image_session.get_db", return_value=db):
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
    with patch("app.core.image_session.get_db", return_value=db):
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
    with patch("app.core.image_session.get_db", return_value=db):
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
    with patch("app.core.image_session.get_db", return_value=db):
        out = image_session.get_session_status("user-1", "sdxl")
    assert out["alive"] is False


def test_stop_session_sets_stopping():
    db = _FakeDB()
    with patch("app.core.image_session.get_db", return_value=db):
        image_session.stop_session("user-1", "s1")
    assert any(op == "update" and vals == {"status": "stopping"} for _t, op, vals in db.calls)


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
    m.assert_called_once_with("test-user-id", "s1", "a cat")


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
