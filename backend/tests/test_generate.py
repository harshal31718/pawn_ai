"""Tests for POST /generate (cube modality) and the generate dispatch.

The Kaggle client is mocked — no real Kaggle calls (testing rule). These verify
routing/validation, the not-configured + failure error shapes, and that the
prompt/input is base64-injected, never interpolated into kernel source.
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
    resp = client.post("/generate", json={"modality": "image", "input": 5})
    assert resp.status_code == 400


def test_generate_requires_input(client):
    resp = client.post("/generate", json={"modality": "cube"})
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
