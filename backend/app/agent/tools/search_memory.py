from app.constants import MEMORY_TOP_K
from app.memory.retrieve import retrieve

from .base import ToolContext, ToolSpec

SEARCH_MEMORY_PARAMETERS = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "What to search for in this chat's (or project's) prior conversation history."},
    },
    "required": ["query"],
}


async def _search_memory_handler(args: dict, ctx: ToolContext) -> str:
    query = args.get("query", "")
    if not query:
        return "TOOL_ERROR: no query provided"
    if not ctx.scope_type or not ctx.scope_id:
        return "TOOL_ERROR: no memory scope for this chat"

    hits = await retrieve(
        query, user_id=ctx.user_id, scope_type=ctx.scope_type, scope_id=ctx.scope_id,
        top_k=MEMORY_TOP_K, match_kind="message",
    )
    if not hits:
        return "No relevant memory found."
    return "\n".join(f"- {h['text']}" for h in hits)


SEARCH_MEMORY_TOOL = ToolSpec(
    name="search_memory",
    description="Searches this chat's (or its project's shared) prior conversation history for relevant context.",
    parameters=SEARCH_MEMORY_PARAMETERS,
    handler=_search_memory_handler,
)
