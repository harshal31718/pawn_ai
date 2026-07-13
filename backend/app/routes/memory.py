"""Memory management surface (Phase M — memory scoping, M.6).

No global tier and no chunk browser — just two user-scoped operations per
scope (chat or project), surfaced via each chat/project kebab's "Memory ▸"
submenu (see plan_memory_scoping.md §5 M.6):

  POST /memory/rebuild — re-derive Postgres memory_chunks for a scope from
                          the Drive rag_chunks.jsonl file(s) (source of truth).
  POST /memory/clear    — delete a scope's memory_chunks rows AND the
                          corresponding rag_chunks.jsonl file(s) on Drive, so
                          cleared memory cannot resurrect via a later rebuild.
"""

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.core.drive_factory import call_drive, require_drive_for_user
from app.db.postgres_client import execute
from app.memory import indexer
from app.storage import conversations_drive, projects_drive

router = APIRouter(prefix="/memory", tags=["memory"])

_VALID_SCOPE_TYPES = {"chat", "project"}


class ScopeRequest(BaseModel):
    scope_type: str
    scope_id: str


def _resolve_conv_ids(drive, scope_type: str, scope_id: str) -> list[str]:
    if scope_type == "chat":
        return [scope_id]
    chat_metas = projects_drive.list_project_chats(drive, scope_id)
    return [m["id"] for m in chat_metas]


def _clear_scope(drive, scope_type: str, scope_id: str) -> None:
    """Overwrite each affected chat's rag_chunks.jsonl to empty. Postgres rows
    for the scope are deleted by the caller before/after this via a plain
    `execute` (kept in the route so it stays visible next to the HTTP layer,
    matching routes/conversations.py's _delete_chunks pattern)."""
    conv_ids = _resolve_conv_ids(drive, scope_type, scope_id)
    for conv_id in conv_ids:
        folder_id = conversations_drive._locate_conv_folder(drive, conv_id)
        if folder_id:
            drive.upload_text("rag_chunks.jsonl", "", folder_id)


def _delete_scope_chunks(user_id: str, scope_type: str, scope_id: str) -> None:
    execute(
        "delete from memory_chunks where user_id = %s and scope_type = %s and scope_id = %s",
        (user_id, scope_type, scope_id),
    )


def _validate_scope(req: ScopeRequest) -> None:
    if req.scope_type not in _VALID_SCOPE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"scope_type must be one of {sorted(_VALID_SCOPE_TYPES)}.",
        )
    if not req.scope_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="scope_id is required.")


@router.post("/rebuild")
async def rebuild_memory(req: ScopeRequest, request: Request):
    _validate_scope(req)
    user_id = request.state.user_id
    # require_drive_for_user is called inside rebuild_index itself; validate scope
    # existence up front so a bogus scope_id gets a clear 404 rather than silently
    # rebuilding zero chunks.
    drive = await run_in_threadpool(require_drive_for_user, user_id)
    if req.scope_type == "chat":
        exists = await run_in_threadpool(call_drive, conversations_drive.get_conversation_meta, drive, req.scope_id)
    else:
        exists = await run_in_threadpool(call_drive, projects_drive.get_project_meta, drive, req.scope_id)
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{req.scope_type} {req.scope_id} not found.",
        )

    count = await indexer.rebuild_index(user_id, req.scope_type, req.scope_id)
    return {"status": "ok", "chunks_indexed": count}


@router.post("/clear")
async def clear_memory(req: ScopeRequest, request: Request):
    _validate_scope(req)
    user_id = request.state.user_id
    drive = await run_in_threadpool(require_drive_for_user, user_id)
    if req.scope_type == "chat":
        exists = await run_in_threadpool(call_drive, conversations_drive.get_conversation_meta, drive, req.scope_id)
    else:
        exists = await run_in_threadpool(call_drive, projects_drive.get_project_meta, drive, req.scope_id)
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{req.scope_type} {req.scope_id} not found.",
        )

    # Drive first (matches this plan's "Drive is authoritative" ordering elsewhere),
    # then Postgres — both layers cleared so rebuild can't resurrect old chunks.
    await run_in_threadpool(call_drive, _clear_scope, drive, req.scope_type, req.scope_id)
    await run_in_threadpool(_delete_scope_chunks, user_id, req.scope_type, req.scope_id)
    return {"status": "ok"}
