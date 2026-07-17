from typing import List

from app.core import key_store

from .base import ToolContext, ToolSpec
from .calculator import CALCULATOR_TOOL
from .doc_search import DOC_SEARCH_TOOL
from .fetch_url import FETCH_URL_TOOL
from .generate_image import GENERATE_IMAGE_TOOL
from .get_datetime import GET_DATETIME_TOOL
from .search_memory import SEARCH_MEMORY_TOOL
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
    search_memory/doc_search (A.4) are added only when ctx.scope_type is not
    None [Phase M] — stateless chats get no memory tools. generate_image
    (F-1) is added only when the user has Kaggle creds configured (same
    key-gating pattern as web_search) — Image Lab's pipeline needs them."""
    tools = list(_ALWAYS_ON)
    if key_store.has_search_key(ctx.user_id):
        tools.append(WEB_SEARCH_TOOL)
    if key_store.has_kaggle_creds(ctx.user_id):
        tools.append(GENERATE_IMAGE_TOOL)
    if ctx.scope_type is not None:
        tools.append(SEARCH_MEMORY_TOOL)
        tools.append(DOC_SEARCH_TOOL)
    return tools
