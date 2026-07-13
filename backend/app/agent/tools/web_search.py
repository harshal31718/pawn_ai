import httpx

from app.constants import WEB_SEARCH_MAX_RESULTS
from app.core import key_store

from .base import ToolContext, ToolSpec

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


def _format_results(results: list[dict]) -> str:
    if not results:
        return "No results found."
    return "\n".join(
        f"{i}. {r['title']} — {r['url']} — {r['snippet']}" for i, r in enumerate(results, start=1)
    )


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

    return _format_results(results)


WEB_SEARCH_TOOL = ToolSpec(
    name="web_search",
    description="Searches the web and returns titles, URLs, and snippets for the top results.",
    parameters=WEB_SEARCH_PARAMETERS,
    handler=_web_search_handler,
)
