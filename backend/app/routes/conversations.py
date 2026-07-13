"""Conversation CRUD routes.

Storage: Google Drive only (no local-filesystem fallback — see
core/drive_factory.py).
"""

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.core.drive_factory import call_drive, require_drive_for_user
from app.storage import conversations_drive as drive_storage

router = APIRouter(prefix="/conversations", tags=["conversations"])


class ConversationCreate(BaseModel):
    id: str | None = None              # client-owned conversation id (optimistic UI)
    title: str = "New Chat"
    model_id: str = "gemini"


class ConversationUpdate(BaseModel):
    title: str


# ─── Blocking storage helpers (run via run_in_threadpool so Drive I/O never
#     executes on the event loop) ───────────────────────────────────────────

def _list(drive, user_id):
    return drive_storage.list_all_conversations(drive)


def _create(drive, user_id, conv_id, title, model_id):
    # Idempotent: if the client-owned id already exists, return the existing meta
    # rather than recreating (a retried create op must never wipe meta/messages).
    if conv_id:
        existing = drive_storage.get_conversation_meta(drive, conv_id)
        if existing:
            return existing
    return drive_storage.create_conversation(drive, user_id=user_id, conv_id=conv_id, title=title, model_id=model_id)


def _get(drive, user_id, conv_id):
    meta = drive_storage.get_conversation_meta(drive, conv_id)
    if not meta:
        return None, None
    return meta, drive_storage.load_messages(drive, conv_id)


def _delete(drive, user_id, conv_id):
    if not drive_storage.get_conversation_meta(drive, conv_id):
        return False
    drive_storage.delete_conversation(drive, conv_id)
    return True


def _update(drive, user_id, conv_id, title):
    if not drive_storage.get_conversation_meta(drive, conv_id):
        return "missing"
    return drive_storage.update_conversation_title(drive, conv_id, title)


def _delete_chunks(user_id, conv_id):
    """Best-effort: delete this chat's Postgres memory_chunks rows (works in
    either scope via the conv_id provenance column). The Drive folder is
    already gone by the time this runs, so a Postgres failure here is logged,
    not surfaced — it's a derived index and can be cleaned up by a rebuild
    once the underlying chat no longer exists on Drive anyway."""
    import sys
    from app.db.postgres_client import execute

    try:
        execute(
            "delete from memory_chunks where user_id = %s and conv_id = %s",
            (user_id, conv_id),
        )
    except Exception as e:
        print(f"Failed to delete memory chunks for {conv_id}: {e}", file=sys.stderr)


@router.get("")
async def list_conversations(request: Request):
    user_id = request.state.user_id
    drive = await run_in_threadpool(require_drive_for_user, user_id)
    return await run_in_threadpool(call_drive, _list, drive, user_id)


@router.post("")
async def create_conversation(req: ConversationCreate, request: Request):
    user_id = request.state.user_id
    drive = await run_in_threadpool(require_drive_for_user, user_id)
    return await run_in_threadpool(call_drive, _create, drive, user_id, req.id, req.title, req.model_id)


@router.get("/{conv_id}")
async def get_conversation(conv_id: str, request: Request):
    user_id = request.state.user_id
    drive = await run_in_threadpool(require_drive_for_user, user_id)
    meta, messages = await run_in_threadpool(call_drive, _get, drive, user_id, conv_id)
    if not meta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Conversation {conv_id} not found.")
    return {"meta": meta, "messages": messages}


@router.delete("/{conv_id}")
async def delete_conversation(conv_id: str, request: Request):
    user_id = request.state.user_id
    drive = await run_in_threadpool(require_drive_for_user, user_id)
    ok = await run_in_threadpool(call_drive, _delete, drive, user_id, conv_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Conversation {conv_id} not found.")
    await run_in_threadpool(_delete_chunks, user_id, conv_id)
    return {"status": "ok"}


@router.patch("/{conv_id}")
async def update_conversation(conv_id: str, req: ConversationUpdate, request: Request):
    user_id = request.state.user_id
    drive = await run_in_threadpool(require_drive_for_user, user_id)
    updated = await run_in_threadpool(call_drive, _update, drive, user_id, conv_id, req.title)
    if updated == "missing":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Conversation {conv_id} not found.")
    if not updated:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update title.")
    return updated
