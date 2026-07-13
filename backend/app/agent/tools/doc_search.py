from typing import Any, Dict, List

from starlette.concurrency import run_in_threadpool

from app.constants import MEMORY_TOP_K
from app.core.drive_factory import call_drive, get_drive_for_user
from app.memory.retrieve import retrieve
from app.storage import conversations_drive

from .base import ToolContext, ToolSpec

DOC_SEARCH_PARAMETERS = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "What to look up in the chat's uploaded document(s)."},
    },
    "required": ["query"],
}


async def _resolve_filenames(user_id: str, hits: List[Dict[str, Any]]) -> Dict[str, str]:
    """Best-effort doc_id -> filename lookup via each hit's originating
    chat's meta.json (conversations_drive.get_attached_docs). Falls back to
    the doc_id itself wherever Drive/meta is unavailable — never blocks the
    observation on a lookup failure."""
    drive = await run_in_threadpool(get_drive_for_user, user_id)
    if drive is None:
        return {}
    filenames: Dict[str, str] = {}
    seen_convs = set()
    for h in hits:
        conv_id = h.get("conv_id")
        if not conv_id or conv_id in seen_convs:
            continue
        seen_convs.add(conv_id)
        try:
            attached = await run_in_threadpool(call_drive, conversations_drive.get_attached_docs, drive, conv_id)
        except Exception:
            continue
        for record in attached:
            if isinstance(record, dict) and record.get("doc_id"):
                filenames[record["doc_id"]] = record.get("filename") or record["doc_id"]
    return filenames


async def _doc_search_handler(args: dict, ctx: ToolContext) -> str:
    query = args.get("query", "")
    if not query:
        return "TOOL_ERROR: no query provided"
    if not ctx.scope_type or not ctx.scope_id:
        return "TOOL_ERROR: no memory scope for this chat"

    hits = await retrieve(
        query, user_id=ctx.user_id, scope_type=ctx.scope_type, scope_id=ctx.scope_id,
        top_k=MEMORY_TOP_K, match_kind="document",
    )
    if not hits:
        return "No relevant document content found."

    filenames = await _resolve_filenames(ctx.user_id, hits)
    lines = []
    for h in hits:
        doc_id = h.get("doc_id")
        label = filenames.get(doc_id, doc_id) if doc_id else "document"
        lines.append(f"[{label}] {h['text']}")
    return "\n".join(lines)


DOC_SEARCH_TOOL = ToolSpec(
    name="doc_search",
    description="Searches this chat's uploaded document(s) for content relevant to the query.",
    parameters=DOC_SEARCH_PARAMETERS,
    handler=_doc_search_handler,
)
