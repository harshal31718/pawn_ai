"""Tests for F-1/F-11: the generate_image agent tool (forced SDXL, always a
warm session) and its registry key-gating."""

from unittest.mock import patch

import pytest

from app.agent.tools.base import ToolContext
from app.agent.tools.generate_image import GENERATE_IMAGE_TOOL, _generate_image_handler
from app.agent.tools.registry import get_tools
from app.core.rate_limiter import EndpointRateLimiter
from app.exceptions import NotConfiguredError
from app.registry.loader import load_registry
from app.resolver.resolver import Resolver


def _ctx():
    resolver = Resolver(load_registry(), EndpointRateLimiter())
    return ToolContext(
        user_id="u1", scope_type=None, scope_id=None,
        resolver=resolver, rate_limiter=resolver._rate_limiter,
    )


def _kaggle_creds(configured: bool):
    return patch(
        "app.core.key_store.get_kaggle",
        return_value={"username": "u", "api_token": "t"} if configured else None,
    )


# ── registry gating ───────────────────────────────────────────────────────────

def test_get_tools_omits_generate_image_without_kaggle_creds():
    with _kaggle_creds(False):
        names = {t.name for t in get_tools(_ctx())}
    assert "generate_image" not in names


def test_get_tools_includes_generate_image_with_kaggle_creds():
    with _kaggle_creds(True):
        names = {t.name for t in get_tools(_ctx())}
    assert "generate_image" in names


def test_get_tools_omits_generate_image_with_partial_kaggle_creds():
    """Username with no token (or vice versa) must not count as configured --
    mirrors has_kaggle_creds requiring both fields."""
    with patch("app.core.key_store.get_kaggle", return_value={"username": "u", "api_token": ""}):
        names = {t.name for t in get_tools(_ctx())}
    assert "generate_image" not in names


# ── _generate_image_handler ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_image_handler_no_prompt_is_tool_error():
    result = await _generate_image_handler({}, _ctx())
    assert result.startswith("TOOL_ERROR")


@pytest.mark.asyncio
async def test_generate_image_handler_uses_warm_session_when_alive():
    """A live session (started from here or from Image Lab -- same
    (user_id, model) row either way) is always reused, never re-started."""
    with patch(
        "app.core.image_session.get_session_status",
        return_value={"alive": True, "session_id": "sess-1", "status": "ready"},
    ):
        with patch("app.core.image_session.submit_session_job", return_value="job-1") as mock_submit:
            with patch("app.core.image_session.start_session") as mock_start:
                result = await _generate_image_handler({"prompt": "a cat"}, _ctx())

    mock_submit.assert_called_once_with("u1", "sess-1", "a cat", None)
    mock_start.assert_not_called()
    assert "job-1" in result
    assert "job_id" in result
    assert "Queued your image on the running SDXL session" in result


@pytest.mark.asyncio
async def test_generate_image_handler_starts_a_new_30min_sdxl_session_when_none_alive():
    """F-11: no live session -> start_session(..., "sdxl", 30, None), never
    the old cold-one-shot path (create_cold_job no longer exists in this
    module at all)."""
    with patch(
        "app.core.image_session.get_session_status",
        return_value={"alive": False, "session_id": None, "status": "none"},
    ):
        with patch(
            "app.core.image_session.start_session",
            return_value={"session_id": "sess-2", "expires_at": "later", "status": "starting"},
        ) as mock_start:
            with patch("app.core.image_session.submit_session_job", return_value="job-2") as mock_submit:
                result = await _generate_image_handler({"prompt": "a dog"}, _ctx())

    mock_start.assert_called_once_with("u1", "sdxl", 30, None)
    mock_submit.assert_called_once_with("u1", "sess-2", "a dog", None)
    assert "job-2" in result
    assert "Started a 30-minute SDXL image session" in result


@pytest.mark.asyncio
async def test_generate_image_handler_ignores_a_model_arg_if_the_llm_sends_one():
    """The tool schema no longer exposes a "model" param (F-11 -- the LLM
    picking flux or malforming the call was the root cause of a live bug),
    but defensively confirm a stray "model" arg in args doesn't change
    behavior -- always sdxl regardless."""
    with patch(
        "app.core.image_session.get_session_status",
        return_value={"alive": True, "session_id": "sess-3", "status": "ready"},
    ) as mock_status:
        with patch("app.core.image_session.submit_session_job", return_value="job-3"):
            await _generate_image_handler({"prompt": "a bird", "model": "flux"}, _ctx())

    mock_status.assert_called_once_with("u1", "sdxl")


@pytest.mark.asyncio
async def test_generate_image_handler_not_configured_becomes_tool_error_not_raise():
    """If Kaggle creds are missing/invalid despite the registry gate having
    passed (e.g. revoked mid-session), the handler must never raise into the
    graph -- run_tool's own never-raises contract is the last line of
    defense, but each tool should degrade gracefully on its own first."""
    with patch(
        "app.core.image_session.get_session_status",
        side_effect=NotConfiguredError("Add your Kaggle username + API token in the Image Lab."),
    ):
        result = await _generate_image_handler({"prompt": "a fox"}, _ctx())
    assert result.startswith("TOOL_ERROR")


@pytest.mark.asyncio
async def test_generate_image_handler_start_session_failure_becomes_tool_error_not_raise():
    """start_session itself can raise NotConfiguredError (no Kaggle creds,
    no PostgREST configured) or KaggleError (deploy failure) -- both
    ProviderError subclasses, must degrade gracefully."""
    with patch(
        "app.core.image_session.get_session_status",
        return_value={"alive": False, "session_id": None, "status": "none"},
    ):
        with patch(
            "app.core.image_session.start_session",
            side_effect=NotConfiguredError("PostgREST isn't configured for warm sessions yet."),
        ):
            result = await _generate_image_handler({"prompt": "a fox"}, _ctx())
    assert result.startswith("TOOL_ERROR")


def test_generate_image_tool_spec_shape():
    assert GENERATE_IMAGE_TOOL.name == "generate_image"
    assert "prompt" in GENERATE_IMAGE_TOOL.parameters["properties"]
    assert GENERATE_IMAGE_TOOL.parameters["required"] == ["prompt"]
    # F-11: the LLM no longer chooses the model -- sdxl only, hardcoded.
    assert "model" not in GENERATE_IMAGE_TOOL.parameters["properties"]
