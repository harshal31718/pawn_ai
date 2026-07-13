import asyncio
import ipaddress
import socket
import urllib.parse

import httpx
import trafilatura

from app.constants import FETCH_MAX_CHARS

from .base import ToolContext, ToolSpec

_ALLOWED_SCHEMES = {"http", "https"}
_MAX_REDIRECTS = 3
_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}


class SSRFBlocked(Exception):
    """Raised when a URL (or a redirect target) fails the SSRF guard."""


async def _resolve_ips(hostname: str) -> list[str]:
    loop = asyncio.get_event_loop()
    try:
        infos = await loop.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise SSRFBlocked(f"could not resolve host '{hostname}': {e}")
    return list({info[4][0] for info in infos})


def _is_blocked_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparseable — refuse rather than risk it
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        # ::ffff:127.0.0.1-style addresses aren't flagged private/loopback by
        # is_private/is_loopback on the IPv6 form itself — a known SSRF-filter
        # bypass. Re-check the embedded IPv4 address instead.
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def guard_url(url: str) -> None:
    """Raises SSRFBlocked if `url` is unsafe to fetch. Must be called BEFORE
    every request — including each individual redirect hop, since a redirect
    can point anywhere. Checks: scheme must be http/https; the hostname is
    resolved and every returned address must be public (no private/loopback/
    link-local/reserved/multicast ranges), which also blocks anything on the
    backend's own network."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise SSRFBlocked(f"scheme '{parsed.scheme}' is not allowed")
    if not parsed.hostname:
        raise SSRFBlocked("URL has no hostname")
    ips = await _resolve_ips(parsed.hostname)
    if not ips:
        raise SSRFBlocked("hostname resolved to no addresses")
    for ip_str in ips:
        if _is_blocked_ip(ip_str):
            raise SSRFBlocked(f"URL resolves to a disallowed address ({ip_str})")


async def _fetch_with_guard(url: str) -> httpx.Response:
    """GETs `url`, re-applying the SSRF guard before the initial request and
    before following each redirect (bounded by _MAX_REDIRECTS). Redirects are
    handled manually (follow_redirects=False) precisely so each hop can be
    re-guarded — httpx's built-in redirect following would bypass the check
    on subsequent hops."""
    current_url = url
    async with httpx.AsyncClient(
        follow_redirects=False, timeout=httpx.Timeout(15.0, connect=5.0)
    ) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            await guard_url(current_url)
            resp = await client.get(current_url)
            if resp.status_code in _REDIRECT_STATUS_CODES and "location" in resp.headers:
                current_url = urllib.parse.urljoin(current_url, resp.headers["location"])
                continue
            return resp
    raise SSRFBlocked("too many redirects")


FETCH_URL_PARAMETERS = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "The http(s) URL to fetch and extract readable text from.",
        }
    },
    "required": ["url"],
}


async def _fetch_url_handler(args: dict, ctx: ToolContext) -> str:
    url = args.get("url", "")
    try:
        resp = await _fetch_with_guard(url)
    except SSRFBlocked as e:
        return f"TOOL_ERROR: refused to fetch URL — {e}"
    except httpx.HTTPError as e:
        return f"TOOL_ERROR: request failed — {e}"

    if resp.status_code >= 400:
        return f"TOOL_ERROR: fetch failed with status {resp.status_code}"

    text = trafilatura.extract(resp.text) or ""
    if not text:
        return "TOOL_ERROR: could not extract readable content from this page"
    return text[:FETCH_MAX_CHARS]


FETCH_URL_TOOL = ToolSpec(
    name="fetch_url",
    description="Fetches a web page and extracts its main readable text content (truncated).",
    parameters=FETCH_URL_PARAMETERS,
    handler=_fetch_url_handler,
)
