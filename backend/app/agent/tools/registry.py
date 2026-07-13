from typing import List

from app.core import key_store

from .base import ToolContext, ToolSpec
from .calculator import CALCULATOR_TOOL
from .fetch_url import FETCH_URL_TOOL
from .get_datetime import GET_DATETIME_TOOL
from .web_search import WEB_SEARCH_TOOL

# Tools unconditionally available in every toolset (no key/scope requirement).
# fetch_url needs no API key itself — its safety comes from the SSRF guard,
# not from key-gating.
_ALWAYS_ON: List[ToolSpec] = [CALCULATOR_TOOL, GET_DATETIME_TOOL, FETCH_URL_TOOL]


def get_tools(ctx: ToolContext) -> List[ToolSpec]:
    """Assembles the per-request toolset. calculator/get_datetime/fetch_url are
    always present. web_search is added only when the user has a Tavily or
    Brave key configured (A.3) — otherwise it's simply absent from the
    toolset (no error; the agent falls back to its own knowledge).
    search_memory/doc_search (A.4) will be added only when ctx.scope_type is
    not None [Phase M] — stateless chats get no memory tools."""
    tools = list(_ALWAYS_ON)
    if key_store.get_key(ctx.user_id, "tavily") or key_store.get_key(ctx.user_id, "brave"):
        tools.append(WEB_SEARCH_TOOL)
    return tools
