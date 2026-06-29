"""Tests for Phase W.1 — the unified durable job layer (cold one-shot path).

This is the lost-result / double-submit bug fix: every image generation becomes a
durable image_jobs row the server tracks. Supabase + Kaggle are mocked.
"""

from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app.core import image_session
from app.exceptions import UnknownModelError
from app.main import app


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Chainable supabase-py table stand-in; records ops and returns seeded rows."""

    def __init__(self, db, table):
        self._db = db
        self._table = table
        self._op = "select"
        self._values = None

    def insert(self, values):
        self._op, self._values = "insert", values
        return self

    def update(self, values):
        self._op, self._values = "update", values
        return self

    def select(self, *_a, **_k):
        self._op = "select"
        return self

    def eq(self, *_a, **_k):
        return self

    def in_(self, *_a, **_k):
        return self

    def is_(self, *_a, **_k):
        return self

    def lt(self, *_a, **_k):
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
            self._db.inserted.append(row)
            return _Result([row])
        if self._op == "update":
            self._db.updates.append((self._table, self._values))
            return _Result([])
        return _Result(list(self._db.rows.get(self._table, [])))


class _FakeDB:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.calls = []
        self.inserted = []
        self.updates = []

    def table(self, name):
        return _Query(self, name)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# --- create_cold_job (de-dup) ------------------------------------------------


def test_create_cold_job_inserts_when_none_active():
    db = _FakeDB(rows={"image_jobs": []})
    with patch("app.core.image_session.get_db", return_value=db):
        job_id, created = image_session.create_cold_job("user-1", "sdxl", "a cat")
    assert created is True
    assert job_id == "image_jobs-id-1"
    row = db.inserted[-1]
    assert row["status"] == "queued"
    assert row["session_id"] is None
    assert row["model"] == "sdxl"
    assert row["prompt"] == "a cat"


def test_create_cold_job_dedups_to_active_job():
    """A second request while one is queued/running returns the SAME id, no insert."""
    db = _FakeDB(rows={"image_jobs": [{"id": "existing", "status": "running"}]})
    with patch("app.core.image_session.get_db", return_value=db):
        job_id, created = image_session.create_cold_job("user-1", "sdxl", "a cat")
    assert created is False
    assert job_id == "existing"
    assert db.inserted == []  # no duplicate row


def test_create_cold_job_unknown_model_raises():
    with pytest.raises(UnknownModelError):
        image_session.create_cold_job("user-1", "nope", "x")


# --- run_cold_job (the background worker) ------------------------------------


def test_run_cold_job_queued_to_done_writes_image():
    db = _FakeDB(rows={"image_jobs": [
        {"id": "j1", "status": "queued", "user_id": "user-1", "prompt": "a cat", "model": "sdxl"}
    ]})
    out = {"image": "PNGBYTES", "mime": "image/png", "via": "kaggle:u/pawn-image-sdxl"}
    with patch("app.core.image_session.get_db", return_value=db), \
         patch("app.core.image_session.generate.generate_image", return_value=out) as gen:
        image_session.run_cold_job("j1")
    gen.assert_called_once_with("user-1", "a cat", "sdxl")
    statuses = [vals.get("status") for _t, vals in db.updates]
    assert statuses == ["running", "done"]
    done = db.updates[-1][1]
    assert done["image_b64"] == "PNGBYTES"
    assert done["via"] == "kaggle:u/pawn-image-sdxl"


def test_run_cold_job_records_error_without_raising():
    db = _FakeDB(rows={"image_jobs": [
        {"id": "j1", "status": "queued", "user_id": "user-1", "prompt": "x", "model": "sdxl"}
    ]})
    with patch("app.core.image_session.get_db", return_value=db), \
         patch("app.core.image_session.generate.generate_image",
               side_effect=RuntimeError("kaggle boom")):
        # Fire-and-forget worker must not raise — it records the error on the row.
        image_session.run_cold_job("j1")
    statuses = [vals.get("status") for _t, vals in db.updates]
    assert statuses == ["running", "error"]
    assert "kaggle boom" in db.updates[-1][1]["error"]


def test_run_cold_job_noop_when_not_queued():
    """De-duped/already-handled job (status != queued) is left untouched."""
    db = _FakeDB(rows={"image_jobs": [{"id": "j1", "status": "running"}]})
    with patch("app.core.image_session.get_db", return_value=db), \
         patch("app.core.image_session.generate.generate_image") as gen:
        image_session.run_cold_job("j1")
    gen.assert_not_called()
    assert db.updates == []


# --- list_jobs ---------------------------------------------------------------


def test_list_jobs_returns_metadata_without_image_bytes():
    rows = [
        {"id": "j2", "session_id": None, "model": "flux", "prompt": "b", "status": "done",
         "mime": "image/png", "via": "v", "created_at": "2026-06-29T01:00:00+00:00"},
        {"id": "j1", "session_id": None, "model": "sdxl", "prompt": "a", "status": "queued",
         "created_at": "2026-06-29T00:00:00+00:00"},
    ]
    db = _FakeDB(rows={"image_jobs": rows})
    with patch("app.core.image_session.get_db", return_value=db):
        out = image_session.list_jobs("user-1")
    assert [j["job_id"] for j in out] == ["j2", "j1"]
    assert out[0]["has_image"] is True   # done
    assert out[1]["has_image"] is False  # queued
    # No image bytes in the list payload (fetched lazily via get_job).
    assert all("image_b64" not in j for j in out)


def test_reap_stale_jobs_marks_stuck_running_as_error():
    """A cold job 'running' past the wall-clock cutoff is transitioned to error."""
    db = _FakeDB()
    with patch("app.core.image_session.get_db", return_value=db):
        image_session.reap_stale_jobs("user-1")
    assert db.updates, "expected a reap update to be issued"
    table, vals = db.updates[-1]
    assert table == "image_jobs"
    assert vals["status"] == "error"
    assert "worker lost" in vals["error"]


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
    mk.assert_called_once_with("test-user-id", "sdxl", "a city")


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
