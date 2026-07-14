import asyncio

import httpx
import trafilatura

from app.constants import (
    WEB_SEARCH_FETCH_CHARS_PER_RESULT,
    WEB_SEARCH_FETCH_TIMEOUT_SECONDS,
    WEB_SEARCH_FETCH_TOP_N,
    WEB_SEARCH_MAX_RESULTS,
)
from app.core import key_store

from .base import ToolContext, ToolSpec
from .fetch_url import SSRFBlocked, _fetch_with_guard

_TIMEOUT = httpx.Timeout(15.0, connect=5.0)

WEB_SEARCH_PARAMETERS = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "The web search query."},
    },
    "required": ["query"],
}


async def _tavily_search(query: str, api_key: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "max_results": WEB_SEARCH_MAX_RESULTS},
        )
        resp.raise_for_status()
        data = resp.json()
    results = data.get("results", [])[:WEB_SEARCH_MAX_RESULTS]
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
        for r in results
    ]


async def _brave_search(query: str, api_key: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": WEB_SEARCH_MAX_RESULTS},
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
    results = data.get("web", {}).get("results", [])[:WEB_SEARCH_MAX_RESULTS]
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("description", "")}
        for r in results
    ]


async def _fetch_body(url: str) -> str | None:
    """Best-effort full-body fetch for one web_search result, reusing
    fetch_url's guarded fetch + trafilatura extraction (O.2, RC-2 fix).
    Returns None on any failure (SSRF-blocked, network error, timeout, no
    extractable content) -- the caller falls back to the search engine's own
    snippet for that result, so one bad/slow fetch never breaks the whole
    search. Bounded by its own timeout (found live: a slow/redirect-heavy
    page can otherwise run past run_tool's outer TOOL_TIMEOUT_SECONDS on its
    own, discarding every result instead of just this one)."""
    try:
        resp = await asyncio.wait_for(_fetch_with_guard(url), timeout=WEB_SEARCH_FETCH_TIMEOUT_SECONDS)
    except (SSRFBlocked, httpx.HTTPError, asyncio.TimeoutError):
        return None
    if resp.status_code >= 400:
        return None
    text = trafilatura.extract(resp.text) or ""
    if not text:
        return None
    return text[:WEB_SEARCH_FETCH_CHARS_PER_RESULT]


async def _enrich_with_bodies(results: list[dict]) -> list[dict]:
    """Fetch+extract the top WEB_SEARCH_FETCH_TOP_N results' full page
    bodies concurrently (not serially -- this must not multiply latency by
    N), replacing each one's snippet with the fetched body on success. The
    remaining, lower-ranked results are left as snippet-only."""
    top = results[:WEB_SEARCH_FETCH_TOP_N]
    if not top:
        return results
    bodies = await asyncio.gather(*(_fetch_body(r["url"]) for r in top))
    for r, body in zip(top, bodies):
        if body:
            r["body"] = body
    return results


def _format_results(results: list[dict]) -> str:
    if not results:
        return "No results found."
    lines = []
    for i, r in enumerate(results, start=1):
        if r.get("body"):
            lines.append(f"{i}. {r['title']} — {r['url']}\n{r['body']}")
        else:
            lines.append(f"{i}. {r['title']} — {r['url']} — {r['snippet']}")
    return "\n\n".join(lines)


async def _web_search_handler(args: dict, ctx: ToolContext) -> str:
    query = args.get("query", "")
    if not query:
        return "TOOL_ERROR: no query provided"

    # Preference order: Tavily first, then Brave (locked in the plan).
    tavily_key = key_store.get_key(ctx.user_id, "tavily")
    brave_key = key_store.get_key(ctx.user_id, "brave") if not tavily_key else None

    if tavily_key:
        results = await _tavily_search(query, tavily_key)
    elif brave_key:
        results = await _brave_search(query, brave_key)
    else:
        return "TOOL_ERROR: no search provider configured"

    results = await _enrich_with_bodies(results)
    return _format_results(results)


WEB_SEARCH_TOOL = ToolSpec(
    name="web_search",
    description="Searches the web and returns titles, URLs, and snippets for the top results.",
    parameters=WEB_SEARCH_PARAMETERS,
    handler=_web_search_handler,
)
