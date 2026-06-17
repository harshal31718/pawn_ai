from typing import Literal
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.normalize import chat_stream, PROVIDERS
from app.exceptions import ProviderError
from app import events
from app.storage.documents import load_doc

router = APIRouter()

# Default provider when none is specified (fastest free tier)
DEFAULT_PROVIDER = "gemini"


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    provider: str = DEFAULT_PROVIDER   # e.g. "groq", "cerebras", "gemini"
    model: str | None = None           # override the provider's default model
    doc_id: str | None = None          # optional uploaded document ID


@router.post("/chat")
async def chat(req: ChatRequest):
    # Retrieve messages from request
    messages = [m.model_dump() for m in req.messages]
    
    # If doc_id is provided, look up and prepend its text
    if req.doc_id:
        doc_text = load_doc(req.doc_id)
        if doc_text is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document with ID {req.doc_id} not found."
            )
        
        system_content = (
            f"Context from uploaded document:\n"
            f"====================\n"
            f"{doc_text}\n"
            f"====================\n"
            f"Answer the user's questions using only the above context."
        )
        # Prepend to message history as a system prompt
        messages.insert(0, {"role": "system", "content": system_content})

    async def generate():
        try:
            async for token in chat_stream(
                req.provider,
                messages,
                model=req.model,
            ):
                yield events.token_event(token)
        except ProviderError as exc:
            yield events.error_event(exc.message)
        yield events.done_event(via_provider=req.provider)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
