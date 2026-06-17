from typing import Literal
from fastapi import APIRouter, HTTPException, status, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.normalize import chat_stream, PROVIDERS
from app.exceptions import ProviderError
from app import events
from app.storage.documents import load_doc
from app.storage import conversations as storage
from app.memory.summarize import summarize_conversation_task

router = APIRouter()

DEFAULT_PROVIDER = "gemini"


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    provider: str = DEFAULT_PROVIDER   # e.g. "groq", "cerebras", "gemini"
    model: str | None = None           # override the provider's default model
    doc_id: str | None = None          # optional uploaded document ID
    conversation_id: str | None = None  # optional conversation ID for persistence


async def generate_title(first_prompt: str) -> str:
    """Helper to generate a short title for the conversation using the first user prompt."""
    system_prompt = (
        "You are a helpful assistant. Generate a short title (max 4-5 words) "
        "for a conversation starting with the user message. Return ONLY the "
        "plain text title, no quote marks, no punctuation, no preamble, no markdown formatting."
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": first_prompt}
    ]
    for provider in ["groq", "cerebras", "gemini"]:
        if provider not in PROVIDERS:
            continue
        try:
            title_text = ""
            async for token in chat_stream(provider, messages):
                title_text += token
            cleaned = title_text.strip().replace('"', '').replace("'", "")
            if cleaned:
                return cleaned
        except Exception:
            continue
    return "New Chat"


async def auto_title_background_task(conv_id: str, first_prompt: str):
    """Background task to generate and save the conversation title."""
    title = await generate_title(first_prompt)
    storage.update_conversation_title(conv_id, title)


@router.post("/chat")
async def chat(req: ChatRequest, request: Request, background_tasks: BackgroundTasks):
    user_msg_dict = None
    
    # 1. Determine base messages
    if req.conversation_id:
        meta = storage.get_conversation_meta(req.conversation_id)
        if not meta:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Conversation {req.conversation_id} not found."
            )
        
        history = storage.load_messages(req.conversation_id)
        
        if not req.messages:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Messages list cannot be empty."
            )
        
        user_msg_dict = req.messages[-1].model_dump()
        raw_messages = history[-10:] if len(history) > 10 else history
        messages_to_send = raw_messages + [user_msg_dict]
        
        summary = storage.load_summary(req.conversation_id)
        if summary:
            summary_system = {
                "role": "system",
                "content": (
                    f"Summary of earlier part of this conversation:\n"
                    f"====================\n"
                    f"{summary}\n"
                    f"===================="
                )
            }
            messages_to_send.insert(0, summary_system)
    else:
        messages_to_send = [m.model_dump() for m in req.messages]
        if messages_to_send:
            user_msg_dict = messages_to_send[-1]
            
    # 2. Inject document context if doc_id provided (in-memory only)
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
        messages_to_send = [{"role": "system", "content": system_content}] + messages_to_send

    # 3. Build inputs and config for LangGraph Agent
    inputs = {
        "conversation_id": req.conversation_id or "stateless",
        "history": messages_to_send,
        "retrieved_memory": [],
        "scratchpad": [],
        "next_action": None,
        "final_answer": None,
        "user_model_id": req.provider,
        "step_count": 0
    }
    
    config = {"configurable": {"thread_id": req.conversation_id or "stateless"}}
    graph = request.app.state.graph

    async def generate():
        if req.provider not in PROVIDERS:
            yield events.error_event(f"Unknown provider: '{req.provider}'. Valid: {list(PROVIDERS)}")
            yield events.done_event(via_provider=req.provider)
            return

        assistant_text = ""
        success = False
        try:
            async for event in graph.astream_events(inputs, config=config, version="v2"):
                kind = event["event"]
                if kind == "on_custom_event":
                    name = event["name"]
                    data = event["data"]
                    if name == "token":
                        delta = data.get("delta", "")
                        assistant_text += delta
                        yield events.token_event(delta)
                    elif name == "step":
                        yield events.step_event(data.get("label", ""), data.get("detail", ""))
                    elif name == "memory_hit":
                        yield events.memory_hit_event(data.get("summary", ""))
                    elif name == "model_call":
                        yield events.model_call_event(data.get("model", ""), data.get("purpose", ""))
            success = True
        except ProviderError as exc:
            yield events.error_event(exc.message)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            yield events.error_event(str(exc))
            
        yield events.done_event(via_provider=req.provider)

        # 4. If persistent and stream succeeded, append user & assistant turns to disk
        if req.conversation_id and success and user_msg_dict and assistant_text:
            assistant_msg_dict = {"role": "assistant", "content": assistant_text}
            storage.append_messages(
                req.conversation_id,
                [user_msg_dict, assistant_msg_dict]
            )
            
            meta = storage.get_conversation_meta(req.conversation_id)
            if meta:
                msg_count = meta.get("message_count", 0)
                if meta.get("title") == "New Chat" and msg_count == 2:
                    background_tasks.add_task(
                        auto_title_background_task,
                        req.conversation_id,
                        user_msg_dict["content"]
                    )
                if msg_count >= 20 and msg_count % 20 == 0:
                    background_tasks.add_task(
                        summarize_conversation_task,
                        req.conversation_id
                    )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


