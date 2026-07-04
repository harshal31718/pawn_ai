"""Tests for Phase W.1 — the unified durable job layer (cold one-shot path).

This is the lost-result / double-submit bug fix: every image generation becomes a
durable image_jobs row the server tracks. Postgres + Kaggle are mocked.
"""

from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app.core import image_session
from app.exceptions import UnknownModelError
from app.main import app


class _FakeDB:
    """Routes fetchone/fetchall/execute to per-table row lists based on simple
    substring sniffing of the SQL text — enough for these tests' shapes."""

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


def _patch_db(db):
    return (
        patch("app.core.image_session.fetchone", side_effect=db.fetchone),
        patch("app.core.image_session.fetchall", side_effect=db.fetchall),
        patch("app.core.image_session.execute", side_effect=db.execute),
    )


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# --- create_cold_job (de-dup) ------------------------------------------------


def test_create_cold_job_inserts_when_none_active():
    db = _FakeDB(rows={"image_jobs": []})
    p1, p2, p3 = _patch_db(db)
    with p1, p2, p3:
        job_id, created = image_session.create_cold_job("user-1", "sdxl", "a cat")
    assert created is True
    assert job_id == "image_jobs-id-1"
    insert_call = next(
        c for c in db.calls if c[0] == "fetchone" and "insert into image_jobs" in c[1]
    )
    params = insert_call[2]
    assert params[0] == "user-1"
    assert params[1] == "sdxl"
    assert params[2] == "a cat"


def test_create_cold_job_dedups_to_active_job():
    """A second request while one is queued/running returns the SAME id, no insert."""
    db = _FakeDB(rows={"image_jobs": [{"id": "existing", "status": "running"}]})
    p1, p2, p3 = _patch_db(db)
    with p1, p2, p3:
        job_id, created = image_session.create_cold_job("user-1", "sdxl", "a cat")
    assert created is False
    assert job_id == "existing"
    assert not any(c[0] == "fetchone" and "insert into" in c[1] for c in db.calls)


def test_create_cold_job_unknown_model_raises():
    with pytest.raises(UnknownModelError):
        image_session.create_cold_job("user-1", "nope", "x")


# --- run_cold_job (the background worker) ------------------------------------


def test_run_cold_job_queued_to_done_writes_image():
    db = _FakeDB(rows={"image_jobs": [
        {"id": "j1", "status": "queued", "user_id": "user-1", "prompt": "a cat", "model": "sdxl"}
    ]})
    out = {"image": "PNGBYTES", "mime": "image/png", "via": "kaggle:u/pawn-image-sdxl"}
    p1, p2, p3 = _patch_db(db)
    with p1, p2, p3, \
         patch("app.core.image_session.generate.generate_image", return_value=out) as gen:
        image_session.run_cold_job("j1")
    gen.assert_called_once_with("user-1", "a cat", "sdxl")

    updates = [c for c in db.calls if c[0] == "execute"]
    assert "'running'" in updates[0][1]
    assert "'done'" in updates[1][1]
    done_params = updates[1][2]
    assert done_params[0] == "PNGBYTES"
    assert done_params[2] == "kaggle:u/pawn-image-sdxl"


def test_run_cold_job_records_error_without_raising():
    db = _FakeDB(rows={"image_jobs": [
        {"id": "j1", "status": "queued", "user_id": "user-1", "prompt": "x", "model": "sdxl"}
    ]})
    p1, p2, p3 = _patch_db(db)
    with p1, p2, p3, \
         patch("app.core.image_session.generate.generate_image",
               side_effect=RuntimeError("kaggle boom")):
        # Fire-and-forget worker must not raise — it records the error on the row.
        image_session.run_cold_job("j1")
    updates = [c for c in db.calls if c[0] == "execute"]
    assert "'running'" in updates[0][1]
    assert "'error'" in updates[1][1]
    assert "kaggle boom" in updates[1][2][0]


def test_run_cold_job_noop_when_not_queued():
    """De-duped/already-handled job (status != queued) is left untouched."""
    db = _FakeDB(rows={"image_jobs": [{"id": "j1", "status": "running"}]})
    p1, p2, p3 = _patch_db(db)
    with p1, p2, p3, \
         patch("app.core.image_session.generate.generate_image") as gen:
        image_session.run_cold_job("j1")
    gen.assert_not_called()
    assert not any(c[0] == "execute" for c in db.calls)


# --- list_jobs ---------------------------------------------------------------


def test_list_jobs_returns_metadata_without_image_bytes():
    rows = [
        {"id": "j2", "session_id": None, "model": "flux", "prompt": "b", "status": "done",
         "mime": "image/png", "via": "v", "created_at": "2026-06-29T01:00:00+00:00"},
        {"id": "j1", "session_id": None, "model": "sdxl", "prompt": "a", "status": "queued",
         "created_at": "2026-06-29T00:00:00+00:00"},
    ]
    db = _FakeDB(rows={"image_jobs": rows})
    p1, p2, p3 = _patch_db(db)
    with p1, p2, p3:
        out = image_session.list_jobs("user-1")
    assert [j["job_id"] for j in out] == ["j2", "j1"]
    assert out[0]["has_image"] is True   # done
    assert out[1]["has_image"] is False  # queued
    # No image bytes in the list payload (fetched lazily via get_job).
    assert all("image_b64" not in j for j in out)


def test_reap_stale_jobs_marks_stuck_cold_as_error():
    """A cold job stuck active past the wall-clock cutoff is transitioned to error."""
    db = _FakeDB()
    p1, p2, p3 = _patch_db(db)
    with p1, p2, p3:
        image_session.reap_stale_jobs("user-1")
    updates = [c for c in db.calls if c[0] == "execute"]
    assert updates, "expected a reap update to be issued"
    sql, params = updates[0][1], updates[0][2]
    assert "'error'" in sql
    assert "worker lost" in sql


def test_reap_stale_jobs_reaps_jobs_of_dead_sessions():
    """Queued and running jobs for a dead session are both reaped so the panel/button
    don't hang on a job the kernel will never pick up."""
    db = _FakeDB(rows={"image_sessions": [{"id": "s-dead", "status": "ended"}]})
    p1, p2, p3 = _patch_db(db)
    with p1, p2, p3:
        image_session.reap_stale_jobs("user-1")
    # cold-reap (unconditional) + queued-session-reap + running-session-reap.
    updates = [c for c in db.calls if c[0] == "execute"]
    session_reap_sqls = [sql for _kind, sql, _params in updates if "session" in sql.lower()]
    assert any("session ended" in sql for sql in session_reap_sqls), "queued-job reap message missing"
    assert any("terminated" in sql.lower() for sql in session_reap_sqls), "running-job reap message missing"


# --- Route: non-blocking POST /generate + GET /generate/jobs -----------------


def test_route_generate_image_is_non_blocking(client):
    """POST /generate {image} returns a job id immediately (the worker is mocked,
    so the response can't have waited on the Kaggle round-trip)."""
    with patch("app.routes.generate.image_session.create_cold_job",
               return_value=("j9", True)) as mk, \
         patch("app.routes.generate.image_session.run_cold_job"):
        resp = client.post("/generate", json={"modality": "image", "prompt": "a city"})
    assert resp.status_code == 200
    assert resp.json() == {"job_id": "j9", "status": "queued"}
    args = mk.call_args.args
    assert args[:3] == ("test-user-id", "sdxl", "a city")


def test_route_generate_image_dedup_skips_worker(client):
    """When create_cold_job de-dups (created=False), no new worker is dispatched."""
    with patch("app.routes.generate.image_session.create_cold_job",
               return_value=("dup", False)), \
         patch("app.routes.generate._run_cold_job_bg") as bg:
        resp = client.post("/generate", json={"modality": "image", "prompt": "a city"})
    assert resp.status_code == 200
    assert resp.json()["job_id"] == "dup"
    bg.assert_not_called()


def test_route_list_jobs(client):
    jobs = [{"job_id": "j1", "model": "flux", "status": "done", "has_image": True}]
    with patch("app.routes.generate.image_session.list_jobs", return_value=jobs) as m:
        resp = client.get("/generate/jobs", params={"model": "flux", "limit": 10})
    assert resp.status_code == 200
    assert resp.json()[0]["job_id"] == "j1"
    m.assert_called_once_with("test-user-id", "flux", 10)
