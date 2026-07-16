"""Tests for F-1: the generate_image agent tool and its registry key-gating."""

import asyncio
from unittest.mock import patch

import pytest

from app.agent.tools.base import ToolContext
from app.agent.tools.generate_image import GENERATE_IMAGE_TOOL, _generate_image_handler
from app.agent.tools.registry import get_tools
from app.core import image_session as image_session_module
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
async def test_generate_image_handler_unknown_model_is_tool_error():
    result = await _generate_image_handler({"prompt": "a cat", "model": "not-a-real-model"}, _ctx())
    assert result.startswith("TOOL_ERROR")
    assert "not-a-real-model" in result


@pytest.mark.asyncio
async def test_generate_image_handler_uses_warm_session_when_alive():
    """A live session must be preferred over a cold one-shot run -- mirrors
    routes/generate.py's own routing (session serves in seconds vs. a full
    cold Kaggle round-trip)."""
    with patch(
        "app.core.image_session.get_session_status",
        return_value={"alive": True, "session_id": "sess-1", "status": "ready"},
    ):
        with patch("app.core.image_session.submit_session_job", return_value="job-1") as mock_submit:
            with patch("app.core.image_session.create_cold_job") as mock_cold:
                result = await _generate_image_handler({"prompt": "a cat"}, _ctx())

    mock_submit.assert_called_once_with("u1", "sess-1", "a cat", None)
    mock_cold.assert_not_called()
    assert "job-1" in result
    assert "job_id" in result


@pytest.mark.asyncio
async def test_generate_image_handler_falls_back_to_cold_job_when_no_session():
    with patch(
        "app.core.image_session.get_session_status",
        return_value={"alive": False, "session_id": None, "status": "none"},
    ):
        with patch("app.core.image_session.create_cold_job", return_value=("job-2", True)) as mock_cold:
            with patch("app.core.image_session.run_cold_job") as mock_run:
                result = await _generate_image_handler({"prompt": "a dog"}, _ctx())
                # run_cold_job is spawned as a fire-and-forget background task on
                # a real threadpool via image_session's own shared registry (F-1
                # fix: shared with routes/generate.py, not a per-module copy) --
                # await it directly while the patches are still active, rather
                # than a bare event-loop tick (not enough to guarantee the
                # threadpool executor has actually run) or awaiting after the
                # `with` blocks exit (the patches would already be reverted).
                await asyncio.gather(*image_session_module._cold_job_bg_tasks)

    mock_cold.assert_called_once_with("u1", "sdxl", "a dog", None)
    assert "job-2" in result
    mock_run.assert_called_once_with("job-2")


@pytest.mark.asyncio
async def test_generate_image_handler_cold_job_dedup_does_not_respawn_worker():
    """create_cold_job returns created=False when de-duping to an already-
    in-flight job -- must NOT spawn a second worker for the same job."""
    with patch(
        "app.core.image_session.get_session_status",
        return_value={"alive": False, "session_id": None, "status": "none"},
    ):
        with patch("app.core.image_session.create_cold_job", return_value=("job-3", False)):
            with patch("app.core.image_session.run_cold_job") as mock_run:
                result = await _generate_image_handler({"prompt": "a bird"}, _ctx())

    await asyncio.sleep(0)
    mock_run.assert_not_called()
    assert "job-3" in result


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


def test_generate_image_tool_spec_shape():
    assert GENERATE_IMAGE_TOOL.name == "generate_image"
    assert "prompt" in GENERATE_IMAGE_TOOL.parameters["properties"]
    assert GENERATE_IMAGE_TOOL.parameters["required"] == ["prompt"]
