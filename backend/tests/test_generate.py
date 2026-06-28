"""Tests for POST /generate and the generate dispatch.

The Kaggle client is mocked — no real Kaggle calls (testing rule).
"""

from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app.exceptions import KaggleError, NotConfiguredError
from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_generate_cube_happy(client):
    result = {"input": 5, "result": 125, "via": "kaggle:u/pawn-cube-poc"}
    with patch("app.routes.generate.generate.generate_cube", return_value=result) as mock_gen:
        resp = client.post("/generate", json={"modality": "cube", "input": 5})
    assert resp.status_code == 200
    assert resp.json()["result"] == 125
    mock_gen.assert_called_once_with("test-user-id", 5)


def test_generate_image_happy(client):
    result = {"image": "b64encoded", "mime": "image/png", "via": "kaggle:u/pawn-image-poc"}
    with patch("app.routes.generate.generate.generate_image", return_value=result) as mock_gen:
        resp = client.post("/generate", json={"modality": "image", "prompt": "a futuristic city"})
    assert resp.status_code == 200
    assert resp.json()["image"] == "b64encoded"
    mock_gen.assert_called_once_with("test-user-id", "a futuristic city")


def test_generate_connect_happy(client):
    with patch("app.routes.generate.generate.connect_kaggle") as mock_connect:
        resp = client.post("/generate/connect")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    mock_connect.assert_called_once_with("test-user-id")


def test_generate_not_configured(client):
    with patch(
        "app.routes.generate.generate.generate_cube",
        side_effect=NotConfiguredError("Add your Kaggle username + API token"),
    ):
        resp = client.post("/generate", json={"modality": "cube", "input": 5})
    assert resp.status_code == 412
    body = resp.json()
    assert body["code"] == "not_configured"
    assert "Kaggle" in body["detail"]


def test_generate_kaggle_failure(client):
    with patch(
        "app.routes.generate.generate.generate_cube",
        side_effect=KaggleError("Kaggle run timed out before completing."),
    ):
        resp = client.post("/generate", json={"modality": "cube", "input": 5})
    assert resp.status_code == 502
    assert resp.json()["code"] == "kaggle"


def test_generate_rejects_unsupported_modality(client):
    resp = client.post("/generate", json={"modality": "video", "prompt": "test"})
    assert resp.status_code == 400


def test_generate_requires_input(client):
    resp = client.post("/generate", json={"modality": "cube"})
    assert resp.status_code == 400


def test_generate_requires_prompt(client):
    resp = client.post("/generate", json={"modality": "image"})
    assert resp.status_code == 400


def test_generate_cube_dispatch_injects_payload_not_source():
    """generate_cube must base64-inject the input, never interpolate it as code."""
    from app.core import generate

    captured = {}

    def fake_run_kernel(**kwargs):
        captured.update(kwargs)
        return b'{"input": 5, "result": 125}'

    cfg = {"username": "alice", "api_token": "tok"}
    with patch("app.core.generate.key_store.get_kaggle", return_value=cfg), \
         patch("app.core.generate.kaggle.run_kernel", side_effect=fake_run_kernel):
        out = generate.generate_cube("user-1", 5)

    assert out["result"] == 125
    assert captured["enable_gpu"] is False
    assert captured["output_filename"] == "out.json"
    # The raw integer must NOT appear as interpolated source; payload is base64.
    assert "\"input\": 5" not in captured["source"]
    assert "__PAWN_PAYLOAD_B64__" not in captured["source"]


def test_generate_cube_dispatch_not_configured():
    from app.core import generate

    with patch("app.core.generate.key_store.get_kaggle", return_value=None):
        with pytest.raises(NotConfiguredError):
            generate.generate_cube("user-1", 5)


class _FakeResp:
    def __init__(self, status_code=200, status="complete"):
        self.status_code = status_code
        self._status = status

    def json(self):
        return {"status": self._status}


class _FakeStatusClient:
    """Returns a sequence of /kernels/status responses on successive GETs."""

    def __init__(self, statuses):
        self._statuses = list(statuses)
        self.calls = 0

    def get(self, path, params=None):
        self.calls += 1
        status = self._statuses.pop(0) if self._statuses else "complete"
        return _FakeResp(200, status)


def test_wait_until_idle_waits_for_inflight_run(monkeypatch):
    """An in-flight (warmup) run is awaited, not rejected, until the slug frees up."""
    from app.core import kaggle

    monkeypatch.setattr(kaggle.time, "sleep", lambda _s: None)
    client = _FakeStatusClient(["running", "queued", "complete"])
    kaggle._wait_until_idle(client, "u", "k", timeout=300, poll_interval=0)
    assert client.calls == 3  # polled until terminal, no KaggleError


def test_wait_until_idle_times_out_if_still_busy(monkeypatch):
    from app.core import kaggle

    monkeypatch.setattr(kaggle.time, "sleep", lambda _s: None)
    # monotonic: deadline=0+timeout; first check under deadline, next check past it.
    ticks = iter([0, 0, 10_000, 10_000])
    monkeypatch.setattr(kaggle.time, "monotonic", lambda: next(ticks))
    client = _FakeStatusClient(["running"] * 5)
    with pytest.raises(KaggleError, match="still busy"):
        kaggle._wait_until_idle(client, "u", "k", timeout=300, poll_interval=0)


def test_wait_until_idle_proceeds_on_non_200():
    """If status can't be read, let the push proceed rather than block forever."""
    from app.core import kaggle

    class _NotFoundClient:
        def get(self, path, params=None):
            return _FakeResp(404, "")

    kaggle._wait_until_idle(_NotFoundClient(), "u", "k", timeout=300, poll_interval=0)
