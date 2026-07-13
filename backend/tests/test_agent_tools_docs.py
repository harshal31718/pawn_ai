"""Tests for A.4: doc_search/search_memory tools and their registry scope-gating."""

from unittest.mock import AsyncMock, patch

import pytest

from app.agent.tools import doc_search as doc_search_module
from app.agent.tools.base import ToolContext
from app.agent.tools.doc_search import DOC_SEARCH_TOOL
from app.agent.tools.execute import run_tool
from app.agent.tools.registry import get_tools
from app.agent.tools.search_memory import SEARCH_MEMORY_TOOL
from app.core.rate_limiter import EndpointRateLimiter
from app.registry.loader import load_registry
from app.resolver.resolver import Resolver


def _ctx(scope_type=None, scope_id=None):
    resolver = Resolver(load_registry(), EndpointRateLimiter(), secrets={})
    return ToolContext(
        user_id="u1", scope_type=scope_type, scope_id=scope_id,
        resolver=resolver, rate_limiter=resolver._rate_limiter,
    )


def _keys(*allowed):
    allowed_set = set(allowed)

    def fake_get_key(user_id, provider):
        return "KEY" if provider in allowed_set else None

    return patch("app.core.key_store.get_key", side_effect=fake_get_key)


# ── registry scope-gating ─────────────────────────────────────────────────────

def test_get_tools_omits_memory_tools_when_stateless():
    with _keys():
        names = {t.name for t in get_tools(_ctx(scope_type=None, scope_id=None))}
    assert "search_memory" not in names
    assert "doc_search" not in names


def test_get_tools_includes_memory_tools_when_scoped():
    with _keys():
        names = {t.name for t in get_tools(_ctx(scope_type="chat", scope_id="c1"))}
    assert "search_memory" in names
    assert "doc_search" in names


# ── search_memory ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_memory_no_scope_returns_tool_error():
    result = await run_tool(SEARCH_MEMORY_TOOL, {"query": "x"}, _ctx())
    assert result.startswith("TOOL_ERROR:")


@pytest.mark.asyncio
async def test_search_memory_calls_retrieve_with_message_kind():
    hits = [{"id": 1, "conv_id": "c1", "text": "earlier fact", "doc_id": None}]
    with patch("app.agent.tools.search_memory.retrieve", new=AsyncMock(return_value=hits)) as mock_retrieve:
        result = await run_tool(SEARCH_MEMORY_TOOL, {"query": "fact"}, _ctx(scope_type="chat", scope_id="c1"))

    assert "earlier fact" in result
    mock_retrieve.assert_called_once()
    assert mock_retrieve.call_args.kwargs["match_kind"] == "message"
    assert mock_retrieve.call_args.kwargs["scope_type"] == "chat"


@pytest.mark.asyncio
async def test_search_memory_no_hits():
    with patch("app.agent.tools.search_memory.retrieve", new=AsyncMock(return_value=[])):
        result = await run_tool(SEARCH_MEMORY_TOOL, {"query": "fact"}, _ctx(scope_type="chat", scope_id="c1"))
    assert "No relevant memory found" in result


# ── doc_search ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_doc_search_no_scope_returns_tool_error():
    result = await run_tool(DOC_SEARCH_TOOL, {"query": "x"}, _ctx())
    assert result.startswith("TOOL_ERROR:")


@pytest.mark.asyncio
async def test_doc_search_calls_retrieve_with_document_kind():
    hits = [{"id": 1, "conv_id": "c1", "text": "page 3 content", "doc_id": "doc-1"}]
    with patch("app.agent.tools.doc_search.retrieve", new=AsyncMock(return_value=hits)) as mock_retrieve:
        with patch.object(doc_search_module, "_resolve_filenames", new=AsyncMock(return_value={})):
            result = await run_tool(DOC_SEARCH_TOOL, {"query": "page 3"}, _ctx(scope_type="chat", scope_id="c1"))

    assert "page 3 content" in result
    mock_retrieve.assert_called_once()
    assert mock_retrieve.call_args.kwargs["match_kind"] == "document"


@pytest.mark.asyncio
async def test_doc_search_prefixes_result_with_filename():
    hits = [{"id": 1, "conv_id": "c1", "text": "budget figures", "doc_id": "doc-1"}]
    with patch("app.agent.tools.doc_search.retrieve", new=AsyncMock(return_value=hits)):
        with patch.object(doc_search_module, "_resolve_filenames", new=AsyncMock(return_value={"doc-1": "budget.pdf"})):
            result = await run_tool(DOC_SEARCH_TOOL, {"query": "budget"}, _ctx(scope_type="chat", scope_id="c1"))

    assert "[budget.pdf]" in result
    assert "budget figures" in result


@pytest.mark.asyncio
async def test_doc_search_falls_back_to_doc_id_when_filename_unresolved():
    hits = [{"id": 1, "conv_id": "c1", "text": "content", "doc_id": "doc-1"}]
    with patch("app.agent.tools.doc_search.retrieve", new=AsyncMock(return_value=hits)):
        with patch.object(doc_search_module, "_resolve_filenames", new=AsyncMock(return_value={})):
            result = await run_tool(DOC_SEARCH_TOOL, {"query": "x"}, _ctx(scope_type="chat", scope_id="c1"))
    assert "[doc-1]" in result


@pytest.mark.asyncio
async def test_doc_search_no_hits():
    with patch("app.agent.tools.doc_search.retrieve", new=AsyncMock(return_value=[])):
        result = await run_tool(DOC_SEARCH_TOOL, {"query": "x"}, _ctx(scope_type="chat", scope_id="c1"))
    assert "No relevant document content found" in result
