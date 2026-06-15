from typing import Literal
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core import llm_core
from app.config import GEMINI_API_KEY
from app.exceptions import ProviderError

router = APIRouter()

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
GEMINI_MODEL = "gemini-2.5-flash"


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


@router.post("/chat")
async def chat(req: ChatRequest):
    headers = {"Authorization": f"Bearer {GEMINI_API_KEY or ''}"}

    async def generate():
        try:
            async for token in llm_core.stream_llm(
                GEMINI_URL,
                GEMINI_MODEL,
                [m.model_dump() for m in req.messages],
                headers,
            ):
                yield f"data: {token}\n\n"
        except ProviderError as exc:
            yield f"data: ERROR: {exc.message}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
