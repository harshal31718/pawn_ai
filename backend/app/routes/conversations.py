from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional

from app.storage import conversations as storage

router = APIRouter(prefix="/conversations", tags=["conversations"])

class ConversationCreate(BaseModel):
    title: str = "New Chat"
    model_id: str = "gemini"

class ConversationUpdate(BaseModel):
    title: str

@router.get("")
async def list_conversations():
    """Lists all saved conversations."""
    return storage.list_conversations()

@router.post("")
async def create_conversation(req: ConversationCreate):
    """Creates a new conversation."""
    return storage.create_conversation(title=req.title, model_id=req.model_id)

@router.get("/{conv_id}")
async def get_conversation(conv_id: str):
    """Retrieves conversation metadata and load all messages."""
    meta = storage.get_conversation_meta(conv_id)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation {conv_id} not found."
        )
    messages = storage.load_messages(conv_id)
    return {
        "meta": meta,
        "messages": messages
    }

@router.delete("/{conv_id}")
async def delete_conversation(conv_id: str):
    """Deletes a conversation by ID."""
    meta = storage.get_conversation_meta(conv_id)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation {conv_id} not found."
        )
    storage.delete_conversation(conv_id)
    return {"status": "ok"}

@router.patch("/{conv_id}")
async def update_conversation(conv_id: str, req: ConversationUpdate):
    """Updates a conversation's title."""
    meta = storage.get_conversation_meta(conv_id)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation {conv_id} not found."
        )
    updated = storage.update_conversation_title(conv_id, req.title)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update conversation title."
        )
    return updated
