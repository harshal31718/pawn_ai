from typing import List

from .base import ToolContext, ToolSpec
from .calculator import CALCULATOR_TOOL
from .get_datetime import GET_DATETIME_TOOL

# Tools unconditionally available in every toolset (no key/scope requirement).
_ALWAYS_ON: List[ToolSpec] = [CALCULATOR_TOOL, GET_DATETIME_TOOL]


def get_tools(ctx: ToolContext) -> List[ToolSpec]:
    """Assembles the per-request toolset. calculator/get_datetime are always
    present. web_search (A.3) will be added only when the user has a search key
    configured; search_memory/doc_search (A.4) will be added only when
    ctx.scope_type is not None [Phase M] — stateless chats get no memory tools."""
    return list(_ALWAYS_ON)
