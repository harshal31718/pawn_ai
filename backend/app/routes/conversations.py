"""Conversation CRUD routes.

Storage priority:
  1. Google Drive (if user has linked Drive via OAuth)
  2. Local filesystem (fallback for tests / pre-Drive-link state)
"""

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.core.drive_factory import get_drive_for_user
from app.storage import conversations as local_storage
from app.storage import conversations_drive as drive_storage

router = APIRouter(prefix="/conversations", tags=["conversations"])


class ConversationCreate(BaseModel):
    title: str = "New Chat"
    model_id: str = "gemini"


class ConversationUpdate(BaseModel):
    title: str


@router.get("")
async def list_conversations(request: Request):
    user_id = request.state.user_id
    drive = get_drive_for_user(user_id)
    if drive:
        return drive_storage.list_conversations(drive)
    return local_storage.list_conversations(user_id=user_id)


@router.post("")
async def create_conversation(req: ConversationCreate, request: Request):
    user_id = request.state.user_id
    drive = get_drive_for_user(user_id)
    if drive:
        return drive_storage.create_conversation(drive, user_id=user_id, title=req.title, model_id=req.model_id)
    return local_storage.create_conversation(user_id=user_id, title=req.title, model_id=req.model_id)


@router.get("/{conv_id}")
async def get_conversation(conv_id: str, request: Request):
    user_id = request.state.user_id
    drive = get_drive_for_user(user_id)
    if drive:
        meta = drive_storage.get_conversation_meta(drive, conv_id)
        if not meta:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Conversation {conv_id} not found.")
        messages = drive_storage.load_messages(drive, conv_id)
    else:
        meta = local_storage.get_conversation_meta(conv_id, user_id=user_id)
        if not meta:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Conversation {conv_id} not found.")
        messages = local_storage.load_messages(conv_id, user_id=user_id)
    return {"meta": meta, "messages": messages}


@router.delete("/{conv_id}")
async def delete_conversation(conv_id: str, request: Request):
    user_id = request.state.user_id
    drive = get_drive_for_user(user_id)
    if drive:
        meta = drive_storage.get_conversation_meta(drive, conv_id)
        if not meta:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Conversation {conv_id} not found.")
        drive_storage.delete_conversation(drive, conv_id)
    else:
        meta = local_storage.get_conversation_meta(conv_id, user_id=user_id)
        if not meta:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Conversation {conv_id} not found.")
        local_storage.delete_conversation(conv_id, user_id=user_id)
    return {"status": "ok"}


@router.patch("/{conv_id}")
async def update_conversation(conv_id: str, req: ConversationUpdate, request: Request):
    user_id = request.state.user_id
    drive = get_drive_for_user(user_id)
    if drive:
        meta = drive_storage.get_conversation_meta(drive, conv_id)
        if not meta:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Conversation {conv_id} not found.")
        updated = drive_storage.update_conversation_title(drive, conv_id, req.title)
    else:
        meta = local_storage.get_conversation_meta(conv_id, user_id=user_id)
        if not meta:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Conversation {conv_id} not found.")
        updated = local_storage.update_conversation_title(conv_id, req.title, user_id=user_id)
    if not updated:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update title.")
    return updated
