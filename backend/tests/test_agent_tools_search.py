"""Tests for A.3: web_search, fetch_url (incl. the SSRF guard), and the
registry's key-gating of web_search."""

import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.tools import fetch_url as fetch_url_module
from app.agent.tools import web_search as web_search_module
from app.agent.tools.base import ToolContext
from app.agent.tools.execute import run_tool
from app.agent.tools.fetch_url import FETCH_URL_TOOL, SSRFBlocked, guard_url
from app.agent.tools.registry import get_tools
from app.agent.tools.web_search import WEB_SEARCH_TOOL
from app.core.rate_limiter import EndpointRateLimiter
from app.registry.loader import load_registry
from app.resolver.resolver import Resolver


def _ctx():
    resolver = Resolver(load_registry(), EndpointRateLimiter())
    return ToolContext(
        user_id="u1", scope_type=None, scope_id=None,
        resolver=resolver, rate_limiter=resolver._rate_limiter,
    )


def _keys(*allowed):
    allowed_set = set(allowed)

    def fake_get_key(user_id, provider):
        return "KEY" if provider in allowed_set else None

    return patch("app.core.key_store.get_key", side_effect=fake_get_key)


# ── registry gating ───────────────────────────────────────────────────────────

def test_get_tools_always_includes_fetch_url():
    with _keys():
        names = {t.name for t in get_tools(_ctx())}
    assert "fetch_url" in names


def test_get_tools_omits_web_search_without_a_key():
    with _keys():
        names = {t.name for t in get_tools(_ctx())}
    assert "web_search" not in names


def test_get_tools_includes_web_search_with_tavily_key():
    with _keys("tavily"):
        names = {t.name for t in get_tools(_ctx())}
    assert "web_search" in names


def test_get_tools_includes_web_search_with_brave_key():
    with _keys("brave"):
        names = {t.name for t in get_tools(_ctx())}
    assert "web_search" in names


# ── web_search ────────────────────────────────────────────────────────────────

def _mock_response(json_body):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = json_body
    return resp


@pytest.mark.asyncio
async def test_web_search_prefers_tavily_over_brave():
    tavily_body = {"results": [{"title": "T", "url": "https://t.example", "content": "snippet"}]}

    with _keys("tavily", "brave"):
        with patch.object(web_search_module.httpx, "AsyncClient") as get_client:
            client = get_client.return_value.__aenter__.return_value
            client.post = AsyncMock(return_value=_mock_response(tavily_body))
            result = await run_tool(WEB_SEARCH_TOOL, {"query": "test"}, _ctx())

    assert "T" in result
    assert "t.example" in result
    client.post.assert_called_once()  # Tavily's POST, not Brave's GET


@pytest.mark.asyncio
async def test_web_search_falls_back_to_brave_when_no_tavily_key():
    brave_body = {"web": {"results": [{"title": "B", "url": "https://b.example", "description": "snippet"}]}}

    with _keys("brave"):
        with patch.object(web_search_module.httpx, "AsyncClient") as get_client:
            client = get_client.return_value.__aenter__.return_value
            client.get = AsyncMock(return_value=_mock_response(brave_body))
            result = await run_tool(WEB_SEARCH_TOOL, {"query": "test"}, _ctx())

    assert "B" in result
    assert "b.example" in result


@pytest.mark.asyncio
async def test_web_search_no_key_returns_tool_error():
    with _keys():
        result = await run_tool(WEB_SEARCH_TOOL, {"query": "test"}, _ctx())
    assert result.startswith("TOOL_ERROR:")


# ── SSRF guard ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_guard_url_rejects_non_http_scheme():
    with pytest.raises(SSRFBlocked):
        await guard_url("ftp://example.com/file")


@pytest.mark.asyncio
async def test_guard_url_rejects_loopback_literal():
    with pytest.raises(SSRFBlocked):
        await guard_url("http://127.0.0.1/admin")


@pytest.mark.asyncio
async def test_guard_url_rejects_localhost_hostname():
    with pytest.raises(SSRFBlocked):
        await guard_url("http://localhost:8000/admin")


@pytest.mark.asyncio
async def test_guard_url_rejects_private_10_range():
    with pytest.raises(SSRFBlocked):
        await guard_url("http://10.0.0.5/secrets")


@pytest.mark.asyncio
async def test_guard_url_rejects_link_local_metadata_ip():
    """169.254.169.254 is the cloud metadata endpoint — a classic SSRF target."""
    with pytest.raises(SSRFBlocked):
        await guard_url("http://169.254.169.254/latest/meta-data/")


@pytest.mark.asyncio
async def test_guard_url_allows_public_ip_literal():
    await guard_url("http://8.8.8.8/")  # public IP — must not raise


@pytest.mark.asyncio
async def test_guard_url_rejects_ipv4_mapped_ipv6_loopback():
    """::ffff:127.0.0.1 is a known SSRF-filter bypass — IPv6Address.is_loopback
    doesn't recognize the embedded IPv4 address unless explicitly unmapped."""
    with pytest.raises(SSRFBlocked):
        await guard_url("http://[::ffff:127.0.0.1]/admin")


@pytest.mark.asyncio
async def test_guard_url_rejects_ipv4_mapped_ipv6_metadata_ip():
    with pytest.raises(SSRFBlocked):
        await guard_url("http://[::ffff:169.254.169.254]/latest/meta-data/")


@pytest.mark.asyncio
async def test_guard_url_rejects_when_dns_resolution_fails():
    async def failing_getaddrinfo(*a, **k):
        raise socket.gaierror("simulated DNS failure")

    fake_loop = MagicMock()
    fake_loop.getaddrinfo = failing_getaddrinfo
    with patch.object(fetch_url_module.asyncio, "get_event_loop", return_value=fake_loop):
        with pytest.raises(SSRFBlocked):
            await guard_url("http://nonexistent.example/")


@pytest.mark.asyncio
async def test_fetch_with_guard_rejects_redirect_to_private():
    """A redirect to a private IP must be rejected on the second hop, not
    silently followed — the guard has to re-check every redirect target."""
    responses = [MagicMock(status_code=302, headers={"location": "http://127.0.0.1/admin"})]

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return responses.pop(0)

    with patch.object(fetch_url_module.httpx, "AsyncClient", FakeClient):
        with pytest.raises(SSRFBlocked):
            await fetch_url_module._fetch_with_guard("http://8.8.8.8/redirector")


@pytest.mark.asyncio
async def test_fetch_with_guard_stops_after_max_redirects():
    responses = [
        MagicMock(status_code=302, headers={"location": "http://8.8.4.4/next"})
        for _ in range(fetch_url_module._MAX_REDIRECTS + 1)
    ]

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return responses.pop(0)

    with patch.object(fetch_url_module.httpx, "AsyncClient", FakeClient):
        with pytest.raises(SSRFBlocked):
            await fetch_url_module._fetch_with_guard("http://8.8.8.8/redirector")


# ── fetch_url tool handler ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_url_handler_extracts_readable_text():
    html = "<html><body><article><p>Hello readable world.</p></article></body></html>"
    resp = MagicMock(status_code=200, text=html)

    async def fake_fetch_with_guard(url):
        return resp

    with patch.object(fetch_url_module, "_fetch_with_guard", side_effect=fake_fetch_with_guard):
        result = await run_tool(FETCH_URL_TOOL, {"url": "http://8.8.8.8/page"}, _ctx())

    assert "TOOL_ERROR" not in result
    assert "readable" in result.lower()


@pytest.mark.asyncio
async def test_fetch_url_handler_blocked_url_returns_tool_error():
    result = await run_tool(FETCH_URL_TOOL, {"url": "http://127.0.0.1/admin"}, _ctx())
    assert result.startswith("TOOL_ERROR:")


@pytest.mark.asyncio
async def test_fetch_url_handler_truncates_to_max_chars():
    long_text = "word " * 5000  # far more than FETCH_MAX_CHARS
    html = f"<html><body><article><p>{long_text}</p></article></body></html>"
    resp = MagicMock(status_code=200, text=html)

    async def fake_fetch_with_guard(url):
        return resp

    with patch.object(fetch_url_module, "_fetch_with_guard", side_effect=fake_fetch_with_guard):
        result = await run_tool(FETCH_URL_TOOL, {"url": "http://8.8.8.8/page"}, _ctx())

    assert len(result) <= fetch_url_module.FETCH_MAX_CHARS
