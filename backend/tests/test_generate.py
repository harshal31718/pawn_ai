"""Tests for POST /generate and the generate dispatch.

The Kaggle client is mocked — no real Kaggle calls (testing rule).
"""

from unittest.mock import AsyncMock, patch

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
        resp = client.post(
            "/generate",
            json={"modality": "image", "prompt": "a futuristic city", "enhance_prompt": "off"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"job_id": "job-1", "status": "queued"}
    # Model defaults to sdxl when omitted; empty params object forwarded.
    args = mk.call_args.args
    assert args[:3] == ("test-user-id", "sdxl", "a futuristic city")
    assert args[3].model_dump(exclude_none=True) == {}
    assert args[4:] == (None, None)  # enhance_prompt: off -> no original/enhanced prompt stored


def test_generate_image_passes_model_through(client):
    with patch(
        "app.routes.generate.image_session.create_cold_job", return_value=("job-2", True)
    ) as mk, patch("app.routes.generate.image_session.run_cold_job"):
        resp = client.post(
            "/generate",
            json={"modality": "image", "prompt": "a city", "model": "flux", "enhance_prompt": "off"},
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


class _FakeStatusOnlyClient:
    """Context-manager fake for kernel_status() -- unlike _FakeStatusClient
    above, this one is entered via `with _client(...) as client:` (mirrors
    _FakeDeployClient's __enter__/__exit__ shape)."""

    def __init__(self, status_code=200, status="running"):
        self.status_code = status_code
        self.status = status
        self.get_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, path, params=None):
        self.get_calls += 1
        return _FakeResp(self.status_code, self.status)


def test_kernel_status_returns_lowercased_status():
    from app.core import kaggle

    fake = _FakeStatusOnlyClient(200, "Error")
    with patch("app.core.kaggle._client", return_value=fake):
        assert kaggle.kernel_status("u", "t", "k") == "error"
    assert fake.get_calls == 1


def test_kernel_status_non_200_returns_none():
    from app.core import kaggle

    fake = _FakeStatusOnlyClient(404, "")
    with patch("app.core.kaggle._client", return_value=fake):
        assert kaggle.kernel_status("u", "t", "k") is None


def test_kernel_status_never_raises_on_client_exception():
    from app.core import kaggle

    def _boom(username, api_token):
        raise RuntimeError("network blip")

    with patch("app.core.kaggle._client", side_effect=_boom):
        assert kaggle.kernel_status("u", "t", "k") is None


def test_kernel_status_missing_status_field_returns_none():
    from app.core import kaggle

    fake = _FakeStatusOnlyClient(200, "")  # {"status": ""} -- falsy
    with patch("app.core.kaggle._client", return_value=fake):
        assert kaggle.kernel_status("u", "t", "k") is None


def test_terminal_kernel_statuses_covers_done_and_failed():
    from app.core import kaggle

    assert kaggle.TERMINAL_KERNEL_STATUSES == kaggle._DONE | kaggle._FAILED
    assert "complete" in kaggle.TERMINAL_KERNEL_STATUSES
    assert "error" in kaggle.TERMINAL_KERNEL_STATUSES
    assert "running" not in kaggle.TERMINAL_KERNEL_STATUSES
    assert "queued" not in kaggle.TERMINAL_KERNEL_STATUSES


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
                "enhance_prompt": "off",
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
            json={
                "modality": "image", "prompt": "a city",
                "params": {"style_preset": "cinematic"}, "enhance_prompt": "off",
            },
        )
    stored_prompt = mk.call_args.args[2]
    assert stored_prompt.startswith("a city")
    assert "cinematic shot" in stored_prompt


def test_generate_image_style_suffix_alone_sets_original_prompt(client):
    """G1: original_prompt must capture the pre-suffix raw text even when the
    enhancer never ran (enhance_prompt=off) -- broadens Q3.1 pass 2's
    enhancement-only original_prompt so the Generations panel can always show
    what the user actually typed, not the suffix-baked-in model prompt."""
    with patch(
        "app.routes.generate.image_session.create_cold_job", return_value=("job-style-orig", True)
    ) as mk, patch("app.routes.generate.image_session.run_cold_job"):
        client.post(
            "/generate",
            json={
                "modality": "image", "prompt": "a city",
                "params": {"style_preset": "cinematic"}, "enhance_prompt": "off",
            },
        )
    stored_prompt = mk.call_args.args[2]
    original_prompt, enhanced_prompt = mk.call_args.args[4], mk.call_args.args[5]
    assert stored_prompt.startswith("a city") and "cinematic shot" in stored_prompt
    assert original_prompt == "a city"
    assert enhanced_prompt is None


def test_generate_image_no_suffix_no_enhancement_leaves_original_prompt_none(client):
    """Nothing changed the prompt -> original_prompt stays None (no duplicate
    of `prompt` stored for the common plain-generation case)."""
    with patch(
        "app.routes.generate.image_session.create_cold_job", return_value=("job-plain", True)
    ) as mk, patch("app.routes.generate.image_session.run_cold_job"):
        client.post(
            "/generate",
            json={"modality": "image", "prompt": "a city", "enhance_prompt": "off"},
        )
    stored_prompt, original_prompt = mk.call_args.args[2], mk.call_args.args[4]
    assert stored_prompt == "a city"
    assert original_prompt is None


def test_generate_image_style_suffix_uses_flux_variant_for_flux_model(client):
    """Q3.3b: per-model suffix variants -- FLUX gets its natural-language
    phrasing, not SDXL's keyword-scaffold suffix, for the same style preset."""
    with patch(
        "app.routes.generate.image_session.create_cold_job", return_value=("job-5", True)
    ) as mk, patch("app.routes.generate.image_session.run_cold_job"):
        client.post(
            "/generate",
            json={
                "modality": "image", "prompt": "a city", "model": "flux",
                "params": {"style_preset": "cinematic"}, "enhance_prompt": "off",
            },
        )
    stored_prompt = mk.call_args.args[2]
    assert "cinematic shot, anamorphic lens" not in stored_prompt  # SDXL's variant
    assert "cinematic film still" in stored_prompt  # FLUX's variant


def test_generate_image_subject_type_suffix_applied(client):
    """Q3.3b: subject-type suffix is appended after the style suffix."""
    with patch(
        "app.routes.generate.image_session.create_cold_job", return_value=("job-6", True)
    ) as mk, patch("app.routes.generate.image_session.run_cold_job"):
        client.post(
            "/generate",
            json={
                "modality": "image", "prompt": "a mountain range",
                "params": {"subject_type": "nature"}, "enhance_prompt": "off",
            },
        )
    stored_prompt = mk.call_args.args[2]
    assert stored_prompt.startswith("a mountain range")
    assert "landscape" in stored_prompt


def test_generate_image_init_image_b64_stored(client):
    """Direct init_image_b64 is merged into params before job creation."""
    fake_b64 = "aGVsbG8="  # base64("hello")
    with patch(
        "app.routes.generate.image_session.create_cold_job", return_value=("job-5", True)
    ) as mk, patch("app.routes.generate.image_session.run_cold_job"):
        resp = client.post(
            "/generate",
            json={
                "modality": "image", "prompt": "a city",
                "init_image_b64": fake_b64, "enhance_prompt": "off",
            },
        )
    assert resp.status_code == 200
    params_arg = mk.call_args.args[3]
    assert params_arg.init_image_b64 == fake_b64
    assert params_arg.strength == 0.6  # default when init image provided


def test_generate_image_init_job_id_resolves(client):
    """init_job_id resolution: fetches the existing job and copies image_b64."""
    fake_b64 = "aW1hZ2U="  # base64("image")
    existing_job = {"job_id": "old-job", "status": "done", "image_b64": fake_b64}
    with patch(
        "app.routes.generate.image_session.get_job", return_value=existing_job
    ), patch(
        "app.routes.generate.image_session.create_cold_job", return_value=("job-6", True)
    ) as mk, patch("app.routes.generate.image_session.run_cold_job"):
        resp = client.post(
            "/generate",
            json={
                "modality": "image", "prompt": "change the sky",
                "init_job_id": "old-job", "enhance_prompt": "off",
            },
        )
    assert resp.status_code == 200
    params_arg = mk.call_args.args[3]
    assert params_arg.init_image_b64 == fake_b64


def test_generate_image_init_job_id_not_found_proceeds(client):
    """If init_job_id resolves to None (missing job), generation still proceeds without init image."""
    with patch(
        "app.routes.generate.image_session.get_job", return_value=None
    ), patch(
        "app.routes.generate.image_session.create_cold_job", return_value=("job-7", True)
    ) as mk, patch("app.routes.generate.image_session.run_cold_job"):
        resp = client.post(
            "/generate",
            json={
                "modality": "image", "prompt": "a city",
                "init_job_id": "missing-job", "enhance_prompt": "off",
            },
        )
    assert resp.status_code == 200
    params_arg = mk.call_args.args[3]
    assert params_arg.init_image_b64 is None


# --- Q3.1 pass 2: vision-grounded prompt enhancer wiring (cold /generate) ---


def test_generate_image_enhance_off_never_calls_enhancer(client):
    with patch(
        "app.routes.generate.image_session.create_cold_job", return_value=("job-8", True)
    ), patch("app.routes.generate.image_session.run_cold_job"), patch(
        "app.core.vision_enhance.enhance_with_vision", new=AsyncMock()
    ) as enh:
        client.post(
            "/generate",
            json={"modality": "image", "prompt": "a cat", "enhance_prompt": "off"},
        )
    enh.assert_not_called()


def test_generate_image_enhance_auto_short_prompt_triggers_enhancer(client):
    """Auto gate: a short/vague prompt is below ENHANCE_SKIP_WORD_THRESHOLD and
    has no scaffold vocabulary -- needs_enhancement() says yes."""
    with patch(
        "app.routes.generate.image_session.create_cold_job", return_value=("job-9", True)
    ) as mk, patch("app.routes.generate.image_session.run_cold_job"), patch(
        "app.core.vision_enhance.enhance_with_vision",
        new=AsyncMock(return_value={
            "prompt": "a fluffy orange cat, 85mm lens, golden hour lighting",
            "negative": "blurry, low quality",
            "used_model": "llama-4-scout",
            "degraded": False,
        }),
    ) as enh:
        resp = client.post(
            "/generate",
            json={"modality": "image", "prompt": "a cat", "enhance_prompt": "auto"},
        )
    assert resp.status_code == 200
    enh.assert_called_once()
    args = mk.call_args.args
    assert args[2] == "a fluffy orange cat, 85mm lens, golden hour lighting"  # prompt used for generation
    assert args[4] == "a cat"  # original_prompt
    assert args[5] == "a fluffy orange cat, 85mm lens, golden hour lighting"  # enhanced_prompt
    params_arg = args[3]
    assert params_arg.negative_prompt == "blurry, low quality"


def test_generate_image_enhance_auto_long_scaffolded_prompt_skips_enhancer(client):
    """Auto gate: an already-detailed, scaffolded prompt is used as-is -- zero
    LLM latency for the common "user already wrote a good prompt" case."""
    scaffolded = (
        "portrait of a woman, shot on 85mm lens, golden hour lighting, "
        "shallow depth of field, bokeh background, film grain, detailed skin "
        "texture, warm color grading, centered composition"
    )
    with patch(
        "app.routes.generate.image_session.create_cold_job", return_value=("job-10", True)
    ) as mk, patch("app.routes.generate.image_session.run_cold_job"), patch(
        "app.core.vision_enhance.enhance_with_vision", new=AsyncMock()
    ) as enh:
        resp = client.post(
            "/generate",
            json={"modality": "image", "prompt": scaffolded, "enhance_prompt": "auto"},
        )
    assert resp.status_code == 200
    enh.assert_not_called()
    args = mk.call_args.args
    assert args[2] == scaffolded
    assert args[4:] == (None, None)


def test_generate_image_enhance_always_forces_call_even_on_long_scaffolded_prompt(client):
    """Always overrides the Auto gate -- the user explicitly asked for the LLM
    pass every time."""
    scaffolded = (
        "portrait of a woman, shot on 85mm lens, golden hour lighting, "
        "shallow depth of field, bokeh background, film grain, detailed skin "
        "texture, warm color grading, centered composition"
    )
    with patch(
        "app.routes.generate.image_session.create_cold_job", return_value=("job-11", True)
    ), patch("app.routes.generate.image_session.run_cold_job"), patch(
        "app.core.vision_enhance.enhance_with_vision",
        new=AsyncMock(return_value={
            "prompt": "rewritten prompt", "negative": None,
            "used_model": "gemini-2.5-flash", "degraded": False,
        }),
    ) as enh:
        resp = client.post(
            "/generate",
            json={"modality": "image", "prompt": scaffolded, "enhance_prompt": "always"},
        )
    assert resp.status_code == 200
    enh.assert_called_once()


def test_generate_image_enhance_degraded_falls_through_to_raw_prompt(client):
    """enhance_with_vision never raises -- a degraded result (no vision model
    available, or every attempt failed) must not block generation, and neither
    prompt field is stored (nothing actually changed)."""
    with patch(
        "app.routes.generate.image_session.create_cold_job", return_value=("job-12", True)
    ) as mk, patch("app.routes.generate.image_session.run_cold_job"), patch(
        "app.core.vision_enhance.enhance_with_vision",
        new=AsyncMock(return_value={
            "prompt": "a cat", "negative": None, "used_model": None, "degraded": True,
        }),
    ):
        resp = client.post(
            "/generate",
            json={"modality": "image", "prompt": "a cat", "enhance_prompt": "auto"},
        )
    assert resp.status_code == 200
    args = mk.call_args.args
    assert args[2] == "a cat"
    assert args[4:] == (None, None)


def test_generate_image_enhance_composes_before_style_suffix(client):
    """Enhancement runs on the raw prompt; style/subject suffixes are appended
    after (Q3.3's existing composition, unchanged by this step)."""
    with patch(
        "app.routes.generate.image_session.create_cold_job", return_value=("job-13", True)
    ) as mk, patch("app.routes.generate.image_session.run_cold_job"), patch(
        "app.core.vision_enhance.enhance_with_vision",
        new=AsyncMock(return_value={
            "prompt": "a fluffy cat, 85mm lens", "negative": None,
            "used_model": "llama-4-scout", "degraded": False,
        }),
    ):
        resp = client.post(
            "/generate",
            json={
                "modality": "image", "prompt": "a cat",
                "params": {"style_preset": "cinematic"}, "enhance_prompt": "always",
            },
        )
    assert resp.status_code == 200
    stored_prompt, original_prompt = mk.call_args.args[2], mk.call_args.args[4]
    assert stored_prompt.startswith("a fluffy cat, 85mm lens")
    assert "cinematic shot" in stored_prompt
    # G1: the enhancer's original_prompt (the true pre-enhancement raw text) must
    # win over the suffix-composition fallback -- appending a style suffix on top
    # of an already-enhanced prompt doesn't change what the user originally typed.
    assert original_prompt == "a cat"


# --- Q3.1 pass 2: vision-grounded prompt enhancer wiring (warm /session/job) ---


def test_session_job_enhance_auto_short_prompt_triggers_enhancer(client):
    with patch(
        "app.routes.generate.image_session.get_session_model", return_value="sdxl"
    ), patch(
        "app.routes.generate.image_session.submit_session_job", return_value="j-enh-1"
    ) as mk, patch(
        "app.core.vision_enhance.enhance_with_vision",
        new=AsyncMock(return_value={
            "prompt": "a fluffy orange cat, 85mm lens, golden hour lighting",
            "negative": "blurry, low quality",
            "used_model": "llama-4-scout",
            "degraded": False,
        }),
    ) as enh:
        resp = client.post(
            "/generate/session/job",
            json={"session_id": "s1", "prompt": "a cat", "enhance_prompt": "auto"},
        )
    assert resp.status_code == 200
    enh.assert_called_once()
    args = mk.call_args.args
    assert args[2] == "a fluffy orange cat, 85mm lens, golden hour lighting"
    assert args[4] == "a cat"
    assert args[5] == "a fluffy orange cat, 85mm lens, golden hour lighting"
    params_arg = args[3]
    assert params_arg.negative_prompt == "blurry, low quality"


def test_session_job_enhance_off_skips_session_model_lookup_when_no_preset(client):
    with patch(
        "app.routes.generate.image_session.get_session_model"
    ) as gm, patch(
        "app.routes.generate.image_session.submit_session_job", return_value="j-enh-2"
    ):
        client.post(
            "/generate/session/job",
            json={"session_id": "s1", "prompt": "a cat", "enhance_prompt": "off"},
        )
    gm.assert_not_called()


def test_session_job_enhance_auto_needs_model_lookup_even_without_preset(client):
    """Auto/Always enhancement needs the session's model to resolve the target
    PromptSchema, even when no style/subject-type preset is set."""
    with patch(
        "app.routes.generate.image_session.get_session_model", return_value="sdxl"
    ) as gm, patch(
        "app.routes.generate.image_session.submit_session_job", return_value="j-enh-3"
    ), patch(
        "app.core.vision_enhance.enhance_with_vision", new=AsyncMock()
    ):
        client.post(
            "/generate/session/job",
            json={"session_id": "s1", "prompt": "a cat", "enhance_prompt": "auto"},
        )
    gm.assert_called_once_with("test-user-id", "s1")


def test_session_job_style_suffix_alone_sets_original_prompt(client):
    """G1: mirrors the cold-path test -- original_prompt captures the raw text
    on the warm session path too when a suffix (not enhancement) is what
    changed the stored prompt."""
    with patch(
        "app.routes.generate.image_session.get_session_model", return_value="sdxl"
    ), patch(
        "app.routes.generate.image_session.submit_session_job", return_value="j-enh-4"
    ) as mk:
        client.post(
            "/generate/session/job",
            json={
                "session_id": "s1", "prompt": "a city",
                "params": {"style_preset": "cinematic"}, "enhance_prompt": "off",
            },
        )
    stored_prompt, original_prompt = mk.call_args.args[2], mk.call_args.args[4]
    assert stored_prompt.startswith("a city") and "cinematic shot" in stored_prompt
    assert original_prompt == "a city"


def test_session_job_enhance_composes_before_style_suffix(client):
    """G1: mirrors the cold-path combined case (test_generate_image_enhance_
    composes_before_style_suffix) on the warm session path -- when both the
    enhancer AND a style suffix run, original_prompt must stay the enhancer's
    true pre-enhancement raw text, not get clobbered by the suffix-only
    fallback in _finalize_original_prompt."""
    with patch(
        "app.routes.generate.image_session.get_session_model", return_value="sdxl"
    ), patch(
        "app.routes.generate.image_session.submit_session_job", return_value="j-enh-5"
    ) as mk, patch(
        "app.core.vision_enhance.enhance_with_vision",
        new=AsyncMock(return_value={
            "prompt": "a fluffy cat, 85mm lens", "negative": None,
            "used_model": "llama-4-scout", "degraded": False,
        }),
    ):
        resp = client.post(
            "/generate/session/job",
            json={
                "session_id": "s1", "prompt": "a cat",
                "params": {"style_preset": "cinematic"}, "enhance_prompt": "always",
            },
        )
    assert resp.status_code == 200
    stored_prompt, original_prompt = mk.call_args.args[2], mk.call_args.args[4]
    assert stored_prompt.startswith("a fluffy cat, 85mm lens")
    assert "cinematic shot" in stored_prompt
    assert original_prompt == "a cat"


def test_session_job_init_image_b64_defaults_strength(client):
    """Regression: params.model_dump() always includes 'strength' as a key
    (None when unset), so dict.setdefault('strength', 0.6) is a no-op --
    must use an explicit is-None check, matching the cold /generate path."""
    fake_b64 = "aGVsbG8="  # base64("hello")
    with patch(
        "app.routes.generate.image_session.submit_session_job", return_value="j-strength-1"
    ) as mk:
        resp = client.post(
            "/generate/session/job",
            json={
                "session_id": "s1", "prompt": "a city",
                "init_image_b64": fake_b64, "enhance_prompt": "off",
            },
        )
    assert resp.status_code == 200
    params_arg = mk.call_args.args[3]
    assert params_arg.init_image_b64 == fake_b64
    assert params_arg.strength == 0.6
