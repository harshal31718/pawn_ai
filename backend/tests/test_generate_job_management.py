"""Tests for imageLab G1: DELETE /generate/job/{id} and POST /generate/jobs/reorder.

image_session.delete_job / reorder_queue are mocked at the route layer (this
file); their own DB-level behavior is covered in test_image_session.py.
"""

from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_delete_job_success(client):
    with patch(
        "app.routes.generate.image_session.delete_job", return_value=True
    ) as mk:
        resp = client.delete("/generate/job/job-1")
    assert resp.status_code == 200
    assert resp.json() == {"status": "deleted"}
    mk.assert_called_once_with("test-user-id", "job-1")


def test_delete_job_conflict_when_not_found_or_running(client):
    with patch("app.routes.generate.image_session.delete_job", return_value=False):
        resp = client.delete("/generate/job/job-1")
    assert resp.status_code == 409


def test_reorder_queue_success(client):
    with patch(
        "app.routes.generate.image_session.reorder_queue", return_value=True
    ) as mk:
        resp = client.post(
            "/generate/jobs/reorder",
            json={"session_id": "s1", "job_ids": ["j3", "j1", "j2"]},
        )
    assert resp.status_code == 200
    assert resp.json() == {"status": "reordered"}
    mk.assert_called_once_with("test-user-id", "s1", ["j3", "j1", "j2"])


def test_reorder_queue_conflict_on_stale_set(client):
    with patch("app.routes.generate.image_session.reorder_queue", return_value=False):
        resp = client.post(
            "/generate/jobs/reorder",
            json={"session_id": "s1", "job_ids": ["j3", "j1"]},
        )
    assert resp.status_code == 409
