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


def test_generate_image_returns_job_id(client):
    """Image generation is now non-blocking: POST returns a job id immediately
    (the slow Kaggle round-trip runs as a background worker)."""
    with patch(
        "app.routes.generate.image_session.create_cold_job", return_value=("job-1", True)
    ) as mk, patch("app.routes.generate.image_session.run_cold_job"):
        resp = client.post("/generate", json={"modality": "image", "prompt": "a futuristic city"})
    assert resp.status_code == 200
    assert resp.json() == {"job_id": "job-1", "status": "queued"}
    # Model defaults to sdxl when omitted; empty params object forwarded.
    args = mk.call_args.args
    assert args[:3] == ("test-user-id", "sdxl", "a futuristic city")
    assert args[3].model_dump(exclude_none=True) == {}


def test_generate_image_passes_model_through(client):
    with patch(
        "app.routes.generate.image_session.create_cold_job", return_value=("job-2", True)
    ) as mk, patch("app.routes.generate.image_session.run_cold_job"):
        resp = client.post(
            "/generate", json={"modality": "image", "prompt": "a city", "model": "flux"}
        )
    assert resp.status_code == 200
    assert resp.json()["job_id"] == "job-2"
    args = mk.call_args.args
    assert args[:3] == ("test-user-id", "flux", "a city")


def test_generate_unknown_model_400(client):
    """An unknown model id is rejected (UnknownModelError → HTTP 400) before any
    job row is created."""
    resp = client.post(
        "/generate", json={"modality": "image", "prompt": "x", "model": "nope"}
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "unknown_model"


def test_generate_connect_happy(client):
    with patch("app.routes.generate.generate.connect_kaggle") as mock_connect:
        resp = client.post("/generate/connect")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    # No body → defaults to sdxl.
    mock_connect.assert_called_once_with("test-user-id", "sdxl")


def test_generate_connect_with_model(client):
    with patch("app.routes.generate.generate.connect_kaggle") as mock_connect:
        resp = client.post("/generate/connect", json={"model": "flux"})
    assert resp.status_code == 200
    mock_connect.assert_called_once_with("test-user-id", "flux")


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


def test_generate_image_dispatch_uses_registry():
    """generate_image must feed run_kernel the registry entry for the chosen model."""
    from app.core import generate
    from app.core.image_models import IMAGE_MODELS

    captured = {}

    def fake_run_kernel(**kwargs):
        captured.update(kwargs)
        return b"\x89PNG fake-bytes"

    cfg = {"username": "alice", "api_token": "tok"}
    with patch("app.core.generate.key_store.get_kaggle", return_value=cfg), \
         patch("app.core.generate.kaggle.run_kernel", side_effect=fake_run_kernel):
        out = generate.generate_image("user-1", "a city", "flux")

    flux = IMAGE_MODELS["flux"]
    assert out["model"] == "flux"
    assert captured["kernel_name"] == flux.slug == "pawn-image-flux"
    assert captured["dataset_sources"] == [flux.dataset]
    assert captured["accelerator"] == flux.accelerator
    assert captured["enable_gpu"] is True
    assert captured["timeout"] == flux.run_timeout
    # Prompt is base64-injected, never interpolated as source.
    assert "a city" not in captured["source"]
    assert "__PAWN_PAYLOAD_B64__" not in captured["source"]


def test_generate_image_unknown_model_raises():
    from app.core import generate
    from app.exceptions import UnknownModelError

    cfg = {"username": "alice", "api_token": "tok"}
    with patch("app.core.generate.key_store.get_kaggle", return_value=cfg):
        with pytest.raises(UnknownModelError):
            generate.generate_image("user-1", "a city", "does-not-exist")


def test_connect_kaggle_warmup_is_dataset_free():
    """Deploy/warmup must not attach the (possibly huge) dataset."""
    from app.core import generate

    captured = {}

    def fake_deploy(**kwargs):
        captured.update(kwargs)

    cfg = {"username": "alice", "api_token": "tok"}
    with patch("app.core.generate.key_store.get_kaggle", return_value=cfg), \
         patch("app.core.generate.kaggle.deploy_kernel", side_effect=fake_deploy):
        generate.connect_kaggle("user-1", "flux")

    assert captured["kernel_name"] == "pawn-image-flux"
    assert captured["dataset_sources"] == []
    assert captured["enable_gpu"] is False


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


class _FakeDeployClient:
    """Records push/status calls so deploy can be asserted non-blocking."""

    def __init__(self, push_status):
        self.push_status = push_status
        self.post_calls = 0
        self.get_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, path, json=None):
        self.post_calls += 1

        class _Resp:
            status_code = self.push_status
            text = "{}"

            def json(_self):
                return {}

        return _Resp()

    def get(self, path, params=None):
        # A status poll here would mean deploy is waiting on a busy slug — it mustn't.
        self.get_calls += 1
        return _FakeResp(200, "running")


def test_deploy_kernel_single_push_when_idle():
    """Deploy is one push, no status polling."""
    from app.core import kaggle

    fake = _FakeDeployClient(push_status=200)
    with patch("app.core.kaggle._client", return_value=fake):
        kaggle.deploy_kernel(
            username="u", api_token="t", kernel_name="k", title="T", source="src"
        )
    assert fake.post_calls == 1
    assert fake.get_calls == 0


def test_kernel_title_slugifies_to_slug():
    """Kaggle derives a notebook's slug from its title; if they disagree the push
    409s ("title already in use"). Guard every registered model against that drift."""
    from app.core import generate
    from app.core.image_models import IMAGE_MODELS

    for spec in IMAGE_MODELS.values():
        title = generate._kernel_title(spec)
        # Kaggle slugify (the part that bit FLUX): lowercase, spaces -> dashes.
        assert title.lower().replace(" ", "-") == spec.slug, spec.id


def test_deploy_kernel_treats_409_as_already_deployed():
    """A busy slug (HTTP 409) means the notebook already exists — deploy returns
    success without blocking, so one model's stuck run can't stall another's deploy."""
    from app.core import kaggle

    fake = _FakeDeployClient(push_status=409)
    with patch("app.core.kaggle._client", return_value=fake):
        kaggle.deploy_kernel(
            username="u", api_token="t", kernel_name="k", title="T", source="src"
        )
    assert fake.post_calls == 1  # single attempt
    assert fake.get_calls == 0  # never waited on the busy slug


def test_generate_image_stores_params(client):
    """Non-default params are forwarded to create_cold_job."""
    with patch(
        "app.routes.generate.image_session.create_cold_job", return_value=("job-3", True)
    ) as mk, patch("app.routes.generate.image_session.run_cold_job"):
        resp = client.post(
            "/generate",
            json={
                "modality": "image",
                "prompt": "a city",
                "params": {"num_inference_steps": 10, "guidance_scale": 5.0},
            },
        )
    assert resp.status_code == 200
    params_arg = mk.call_args.args[3]
    assert params_arg.num_inference_steps == 10
    assert params_arg.guidance_scale == 5.0


def test_generate_image_style_suffix_applied(client):
    """Style preset suffix is appended to the prompt before the job is created."""
    with patch(
        "app.routes.generate.image_session.create_cold_job", return_value=("job-4", True)
    ) as mk, patch("app.routes.generate.image_session.run_cold_job"):
        client.post(
            "/generate",
            json={"modality": "image", "prompt": "a city", "params": {"style_preset": "cinematic"}},
        )
    stored_prompt = mk.call_args.args[2]
    assert stored_prompt.startswith("a city")
    assert "cinematic shot" in stored_prompt
