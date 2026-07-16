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


@pytest.fixture(autouse=True)
def _clear_kernel_probe_cache():
    """_probe_cache is module-level state keyed by session_id, and most tests
    in this file reuse the same fake id ("s1") -- without clearing it, a
    probe result cached by one test could leak into the next (well within
    the 30s throttle window between fast-running tests)."""
    image_session._probe_cache.clear()
    yield
    image_session._probe_cache.clear()


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


def test_submit_session_job_snaps_old_sd15_resolution_to_native_bucket():
    """Q1.1 server-side guard applies on the warm-session job path too."""
    now = datetime.now(timezone.utc)
    live = {
        "id": "s1",
        "user_id": "user-1",
        "model": "sdxl",
        "status": "ready",
        "expires_at": _iso(now + timedelta(minutes=30)),
        "heartbeat_at": _iso(now),
    }
    db = _FakeDB(rows={"image_sessions": [live]})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4:
        image_session.submit_session_job(
            "user-1", "s1", "a red apple",
            image_session.ImageJobParams(width=576, height=1024),
        )
    insert_call = next(
        c for c in db.calls if c[0] == "fetchone" and "insert into image_jobs" in c[1]
    )
    stored_params = insert_call[2][4].obj
    assert stored_params["width"] == 768
    assert stored_params["height"] == 1344


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
    assert out["status"] == "ready"
    assert out["error"] is None
    # A healthy session must never be written back to -- no execute calls at all.
    assert not any(kind == "execute" for kind, _, _ in db.calls)


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
    # A silently-dead kernel must now be persisted as 'error', not left as 'ready'.
    assert out["status"] == "error"
    assert out["error"] and "heartbeat" in out["error"].lower()
    assert any(
        kind == "execute" and "status = 'error'" in sql and "status = 'ready'" in sql
        for kind, sql, params in db.calls
    )


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
    assert out["status"] == "error"
    assert out["error"] and "time limit" in out["error"].lower()


def test_get_session_status_warmup_stale_heartbeat_flips_to_error():
    """The supervisor heartbeats during warmup, so a stale heartbeat on a
    still-loading session means the kernel died mid-startup (crash/OOM/killed)."""
    now = datetime.now(timezone.utc)
    row = {
        "id": "s1",
        "status": "loading_model",
        "expires_at": _iso(now + timedelta(minutes=30)),
        "heartbeat_at": _iso(now - timedelta(minutes=5)),  # stale during warmup
        "created_at": _iso(now - timedelta(minutes=6)),
        "images_done": 0,
    }
    db = _FakeDB(rows={"image_sessions": [row]})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4:
        out = image_session.get_session_status("user-1", "flux")
    assert out["status"] == "error"
    assert out["error"] and "during startup" in out["error"]
    assert any(kind == "execute" and "status = 'error'" in sql for kind, sql, _ in db.calls)


def test_get_session_status_warmup_fresh_heartbeat_stays_loading():
    """A warming-up session that IS still heartbeating must stay in its phase,
    not be reaped -- even though it hasn't reached 'ready' yet."""
    now = datetime.now(timezone.utc)
    row = {
        "id": "s1",
        "status": "loading_model",
        "expires_at": _iso(now + timedelta(minutes=30)),
        "heartbeat_at": _iso(now - timedelta(seconds=5)),  # fresh
        "created_at": _iso(now - timedelta(minutes=3)),
        "images_done": 0,
    }
    db = _FakeDB(rows={"image_sessions": [row]})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4:
        out = image_session.get_session_status("user-1", "flux")
    assert out["status"] == "loading_model"
    assert not any(kind == "execute" for kind, _, _ in db.calls)


def test_get_session_status_warmup_no_heartbeat_falls_back_to_timeout():
    """Before the first heartbeat lands (or an old notebook), warmup death is
    detected via the wall-clock startup timeout, not heartbeat staleness --
    the age here (20min) is past the probe-eligible window too, so the probe
    is mocked returning None (no info, e.g. no Kaggle creds) to prove the
    900s backstop still fires on its own when the probe can't help."""
    now = datetime.now(timezone.utc)
    row = {
        "id": "s1",
        "status": "starting",
        "expires_at": _iso(now + timedelta(minutes=30)),
        "heartbeat_at": None,
        "created_at": _iso(now - timedelta(minutes=20)),  # past 15min startup timeout
        "images_done": 0,
    }
    db = _FakeDB(rows={"image_sessions": [row]})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4, patch("app.core.image_session.key_store.get_kaggle", return_value=None):
        out = image_session.get_session_status("user-1", "flux")
    assert out["status"] == "error"
    assert out["error"] and "starting up" in out["error"]


def test_get_session_status_warmup_no_heartbeat_recent_stays_starting():
    """A just-started session (no heartbeat yet, recent created_at) must not be
    prematurely killed."""
    now = datetime.now(timezone.utc)
    row = {
        "id": "s1",
        "status": "starting",
        "expires_at": _iso(now + timedelta(minutes=30)),
        "heartbeat_at": None,
        "created_at": _iso(now - timedelta(seconds=10)),  # just started
        "images_done": 0,
    }
    db = _FakeDB(rows={"image_sessions": [row]})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4:
        out = image_session.get_session_status("user-1", "flux")
    assert out["status"] == "starting"
    assert not any(kind == "execute" for kind, _, _ in db.calls)


# --- Kaggle kernel-status probe (dead-session detection) ---------------------

_KAGGLE_CFG = {"username": "alice", "api_token": "tok"}


def _row_no_heartbeat(now, age_seconds, **overrides):
    row = {
        "id": "s1",
        "status": "loading_model",
        "expires_at": _iso(now + timedelta(minutes=30)),
        "heartbeat_at": None,
        "created_at": _iso(now - timedelta(seconds=age_seconds)),
        "images_done": 0,
    }
    row.update(overrides)
    return row


def test_get_session_status_probe_terminal_status_flips_early():
    """Kaggle reporting the kernel already 'error'd/completed is a much faster,
    more precise signal than waiting out the full 900s wall-clock timeout."""
    now = datetime.now(timezone.utc)
    row = _row_no_heartbeat(now, 120)  # past the 60s probe-eligible age, well under 900s
    db = _FakeDB(rows={"image_sessions": [row]})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4, \
         patch("app.core.image_session.key_store.get_kaggle", return_value=_KAGGLE_CFG), \
         patch("app.core.image_session.kaggle.kernel_status", return_value="error") as mock_probe:
        out = image_session.get_session_status("user-1", "flux")
    assert out["status"] == "error"
    assert out["error"] and "no longer running" in out["error"] and "'error'" in out["error"]
    mock_probe.assert_called_once_with("alice", "tok", "pawn-flux-session")


def test_get_session_status_probe_complete_status_also_flips():
    now = datetime.now(timezone.utc)
    row = _row_no_heartbeat(now, 120)
    db = _FakeDB(rows={"image_sessions": [row]})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4, \
         patch("app.core.image_session.key_store.get_kaggle", return_value=_KAGGLE_CFG), \
         patch("app.core.image_session.kaggle.kernel_status", return_value="complete"):
        out = image_session.get_session_status("user-1", "flux")
    assert out["status"] == "error"
    assert out["error"] and "no longer running" in out["error"]


def test_get_session_status_probe_queued_stays_warming_and_suppresses_900s_backstop():
    """A kernel that's still queued on Kaggle (GPU queue) is legitimately not
    up yet -- the probe reporting 'queued' must suppress even the 900s
    wall-clock backstop, not just the fast-path checks."""
    now = datetime.now(timezone.utc)
    row = _row_no_heartbeat(now, 1000)  # past the old 900s backstop
    db = _FakeDB(rows={"image_sessions": [row]})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4, \
         patch("app.core.image_session.key_store.get_kaggle", return_value=_KAGGLE_CFG), \
         patch("app.core.image_session.kaggle.kernel_status", return_value="queued"):
        out = image_session.get_session_status("user-1", "flux")
    assert out["status"] == "loading_model"
    assert not any(kind == "execute" for kind, _, _ in db.calls)


def test_get_session_status_probe_running_recent_stays_warming():
    """Kaggle says the kernel is running and it just hasn't had time to reach
    PAWN's database yet -- must not be flagged before the rendezvous-broken
    window (180s) elapses."""
    now = datetime.now(timezone.utc)
    row = _row_no_heartbeat(now, 90)  # past 60s probe-eligible, under 180s rendezvous window
    db = _FakeDB(rows={"image_sessions": [row]})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4, \
         patch("app.core.image_session.key_store.get_kaggle", return_value=_KAGGLE_CFG), \
         patch("app.core.image_session.kaggle.kernel_status", return_value="running"):
        out = image_session.get_session_status("user-1", "flux")
    assert out["status"] == "loading_model"
    assert not any(kind == "execute" for kind, _, _ in db.calls)


def test_get_session_status_probe_running_no_heartbeat_past_180s_flips_with_rendezvous_message():
    """Kaggle says running, but PAWN has never heard from it -- the kernel is
    alive but can't reach PostgREST at all (tunnel down, RLS mismatch)."""
    now = datetime.now(timezone.utc)
    row = _row_no_heartbeat(now, 200)  # past the 180s rendezvous-broken window
    db = _FakeDB(rows={"image_sessions": [row]})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4, \
         patch("app.core.image_session.key_store.get_kaggle", return_value=_KAGGLE_CFG), \
         patch("app.core.image_session.kaggle.kernel_status", return_value="running"):
        out = image_session.get_session_status("user-1", "flux")
    assert out["status"] == "error"
    assert out["error"] and "never reached PAWN's database" in out["error"]


def test_get_session_status_probe_no_creds_skips_probe_entirely():
    """No Kaggle creds configured -- _kernel_probe must return None without
    ever calling kaggle.kernel_status, falling back to the old timeout path."""
    now = datetime.now(timezone.utc)
    row = _row_no_heartbeat(now, 120)
    db = _FakeDB(rows={"image_sessions": [row]})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4, \
         patch("app.core.image_session.key_store.get_kaggle", return_value=None), \
         patch("app.core.image_session.kaggle.kernel_status") as mock_probe:
        out = image_session.get_session_status("user-1", "flux")
    assert out["status"] == "loading_model"  # not yet past the 900s backstop
    mock_probe.assert_not_called()


def test_get_session_status_probe_throttled_within_window():
    """Two get_session_status calls in quick succession must only hit Kaggle's
    API once -- the frontend polls every 3s, Kaggle shouldn't be hammered."""
    now = datetime.now(timezone.utc)
    row = _row_no_heartbeat(now, 120)
    db = _FakeDB(rows={"image_sessions": [row]})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4, \
         patch("app.core.image_session.key_store.get_kaggle", return_value=_KAGGLE_CFG), \
         patch("app.core.image_session.kaggle.kernel_status", return_value="running") as mock_probe:
        image_session.get_session_status("user-1", "flux")
        image_session.get_session_status("user-1", "flux")
    assert mock_probe.call_count == 1


def test_get_session_status_probe_early_check_on_half_stale_heartbeat():
    """A heartbeat that's gone stale past half the 90s window (but not the
    full window yet) triggers an early probe check rather than waiting out
    the remaining time when Kaggle can already confirm the kernel is over."""
    now = datetime.now(timezone.utc)
    row = {
        "id": "s1",
        "status": "loading_model",
        "expires_at": _iso(now + timedelta(minutes=30)),
        "heartbeat_at": _iso(now - timedelta(seconds=50)),  # > 45s half-window, < 90s full window
        "created_at": _iso(now - timedelta(minutes=3)),
        "images_done": 0,
    }
    db = _FakeDB(rows={"image_sessions": [row]})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4, \
         patch("app.core.image_session.key_store.get_kaggle", return_value=_KAGGLE_CFG), \
         patch("app.core.image_session.kaggle.kernel_status", return_value="error"):
        out = image_session.get_session_status("user-1", "flux")
    assert out["status"] == "error"
    assert out["error"] and "no longer running" in out["error"]


def test_get_session_status_includes_created_at():
    now = datetime.now(timezone.utc)
    row = {
        "id": "s1",
        "status": "ready",
        "expires_at": _iso(now + timedelta(minutes=30)),
        "heartbeat_at": _iso(now),
        "created_at": _iso(now - timedelta(minutes=2)),
        "images_done": 0,
    }
    db = _FakeDB(rows={"image_sessions": [row]})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4:
        out = image_session.get_session_status("user-1", "sdxl")
    assert out["created_at"] == row["created_at"]


def test_get_session_status_stopping_within_grace_period_untouched():
    """A Stop just clicked on a long-running session must NOT be immediately
    declared 'ended' -- this was the exact bug: age was measured from the
    session's original created_at (always old) instead of stop_requested_at."""
    now = datetime.now(timezone.utc)
    row = {
        "id": "s1",
        "status": "stopping",
        "created_at": _iso(now - timedelta(hours=1)),  # session has run a long time
        "stop_requested_at": _iso(now - timedelta(seconds=5)),  # stop just clicked
        "expires_at": _iso(now + timedelta(minutes=30)),
        "images_done": 0,
    }
    db = _FakeDB(rows={"image_sessions": [row]})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4:
        out = image_session.get_session_status("user-1", "sdxl")
    assert out["status"] == "stopping"
    assert not any(kind == "execute" for kind, _, _ in db.calls)


def test_get_session_status_stopping_past_grace_period_flips_to_error():
    now = datetime.now(timezone.utc)
    row = {
        "id": "s1",
        "status": "stopping",
        "created_at": _iso(now - timedelta(hours=1)),
        "stop_requested_at": _iso(now - timedelta(seconds=45)),  # past the 30s grace period
        "expires_at": _iso(now + timedelta(minutes=30)),
        "images_done": 0,
    }
    db = _FakeDB(rows={"image_sessions": [row]})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4:
        out = image_session.get_session_status("user-1", "sdxl")
    assert out["status"] == "error"
    assert out["alive"] is False
    assert out["error"] and "didn't confirm exit" in out["error"]
    assert any(kind == "execute" and "status = 'error'" in sql for kind, sql, _ in db.calls)


def test_get_session_status_stopping_confirmed_ended_untouched():
    """If the kernel cooperatively patched status to 'ended' before the grace
    period elapsed, get_session_status must not overwrite it with anything."""
    now = datetime.now(timezone.utc)
    row = {
        "id": "s1",
        "status": "ended",
        "created_at": _iso(now - timedelta(hours=1)),
        "stop_requested_at": _iso(now - timedelta(seconds=45)),
        "expires_at": _iso(now + timedelta(minutes=30)),
        "images_done": 0,
    }
    db = _FakeDB(rows={"image_sessions": [row]})
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4:
        out = image_session.get_session_status("user-1", "sdxl")
    assert out["status"] == "ended"
    assert not any(kind == "execute" for kind, _, _ in db.calls)


def test_stop_session_sets_stopping():
    db = _FakeDB()
    p1, p2, p3, p4 = _patch_db(db)
    with p1, p2, p3, p4:
        image_session.stop_session("user-1", "s1")
    assert any(
        kind == "execute" and "'stopping'" in sql and "stop_requested_at" in sql
        and params == ("s1", "user-1")
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
