from typing import Literal
from fastapi import APIRouter, HTTPException, status, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.core.normalize import chat_stream
from app.resolver.resolver import Resolver
from app.core.rate_limiter import EndpointRateLimiter
from app.exceptions import ProviderError
from app import events
from app.core import key_store
from app.core.drive_factory import get_drive_for_user
from app.storage import documents_drive
from app.storage import conversations_drive
from app.storage.documents import load_doc
from app.storage import conversations as local_storage
from app.memory.summarize import summarize_conversation_task

router = APIRouter()


def _load_conversation_bundle(drive, conv_id: str, user_id: str | None):
    """Blocking: load (meta, history, summary) for an existing conversation in one
    threadpool hop. Returns (None, [], None) when the conversation doesn't exist."""
    if drive:
        meta = conversations_drive.get_conversation_meta(drive, conv_id)
        if not meta:
            return None, [], None
        history = conversations_drive.load_messages(drive, conv_id)
        summary = conversations_drive.load_summary(drive, conv_id)
    else:
        meta = local_storage.get_conversation_meta(conv_id, user_id=user_id)
        if not meta:
            return None, [], None
        history = local_storage.load_messages(conv_id, user_id=user_id)
        summary = local_storage.load_summary(conv_id, user_id=user_id)
    return meta, history, summary


def _persist_turn(drive, conv_id: str, user_id: str | None, turns: list[dict]):
    """Blocking: append the user+assistant turns and return the refreshed meta."""
    if drive:
        conversations_drive.append_messages(drive, conv_id, turns)
        return conversations_drive.get_conversation_meta(drive, conv_id)
    local_storage.append_messages(conv_id, turns, user_id=user_id)
    return local_storage.get_conversation_meta(conv_id, user_id=user_id)


def _create_with_id(drive, conv_id: str, user_id: str | None, model_id: str):
    """Blocking: materialize a client-owned conversation id (lazy-create on first message)."""
    if drive:
        return conversations_drive.create_conversation(
            drive, user_id=user_id, conv_id=conv_id, title="New Chat", model_id=model_id
        )
    return local_storage.create_conversation(
        user_id=user_id, conv_id=conv_id, title="New Chat", model_id=model_id
    )

class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str

class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    model_id: str | None = None        # Canonical model ID (e.g. "gemini-2.5-flash", "llama-3.3-70b")
    provider: str | None = None        # Backward compatibility for provider selection
    doc_id: str | None = None          # optional uploaded document ID
    conversation_id: str | None = None  # optional conversation ID for persistence

async def generate_title(first_prompt: str, resolver: Resolver, rate_limiter: EndpointRateLimiter, user_id: str | None = None) -> str:
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
    try:
        model_id = resolver.pick_model_by_capability("fast")
        title_text = ""
        async for token in chat_stream(model_id, messages, resolver, rate_limiter, user_id=user_id):
            title_text += token
        cleaned = title_text.strip().replace('"', '').replace("'", "")
        if cleaned:
            return cleaned
    except Exception:
        pass
    return "New Chat"

async def auto_title_background_task(conv_id: str, first_prompt: str, resolver: Resolver, rate_limiter: EndpointRateLimiter, user_id: str | None = None):
    """Background task to generate and save the conversation title."""
    title = await generate_title(first_prompt, resolver, rate_limiter, user_id=user_id)
    drive = await run_in_threadpool(get_drive_for_user, user_id) if user_id else None
    if drive:
        await run_in_threadpool(conversations_drive.update_conversation_title, drive, conv_id, title)
    else:
        await run_in_threadpool(local_storage.update_conversation_title, conv_id, title, user_id=user_id)

@router.post("/chat")
async def chat(req: ChatRequest, request: Request, background_tasks: BackgroundTasks):
    user_msg_dict = None
    user_id = request.state.user_id
    resolver = request.app.state.resolver
    rate_limiter = request.app.state.rate_limiter
    # Blocking I/O (Supabase/Drive) is run off the event loop so a slow backend
    # can't stall every other in-flight request.
    drive = await run_in_threadpool(get_drive_for_user, user_id)
    # Warm the per-user BYOK key cache once so the resolver's in-graph get_key()
    # calls are cache hits instead of blocking Supabase round-trips on the loop.
    await run_in_threadpool(key_store.prefetch, user_id)

    # Resolve canonical model_id from input
    model_id = req.model_id
    if not model_id:
        model_id = req.provider or "gemini-2.5-flash"

    # Check if the model_id exists in the registry or friendly provider map
    if not resolver._registry.get_model(model_id) and model_id not in ["google", "gemini", "cerebras", "groq", "huggingface", "github", "openrouter"]:
        async def generate_error():
            yield events.error_event(f"Unknown model or provider: '{model_id}'")
            yield events.done_event(via_provider="unknown")

        return StreamingResponse(
            generate_error(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    if req.conversation_id:
        meta, history, summary = await run_in_threadpool(
            _load_conversation_bundle, drive, req.conversation_id, user_id
        )
        if not meta:
            # The client owns the conversation id (optimistic UI). If the background
            # create op hasn't landed yet, materialize it now so the first message
            # is never lost to a 404 — the flow stays fail-proof.
            await run_in_threadpool(_create_with_id, drive, req.conversation_id, user_id, model_id)
            history, summary = [], None

        if not req.messages:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Messages list cannot be empty."
            )

        user_msg_dict = req.messages[-1].model_dump()
        raw_messages = history[-10:] if len(history) > 10 else history
        messages_to_send = raw_messages + [user_msg_dict]

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

    # 2. Inject document context if doc_id provided
    if req.doc_id:
        if drive:
            doc_text = await run_in_threadpool(documents_drive.load_doc, req.doc_id, drive)
        else:
            doc_text = await run_in_threadpool(load_doc, req.doc_id, user_id=user_id)
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
        "user_id": user_id,
        "history": messages_to_send,
        "retrieved_memory": [],
        "scratchpad": [],
        "next_action": None,
        "final_answer": None,
        "user_model_id": model_id,
        "step_count": 0
    }
    
    thread_id = f"{user_id}:{req.conversation_id}" if req.conversation_id else f"{user_id}:stateless"
    config = {"configurable": {"thread_id": thread_id}}
    graph = request.app.state.graph

    async def generate():
        assistant_text = ""
        success = False
        active_provider = "unknown"
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
                    elif name == "provider_switch":
                        yield events.provider_switch_event(data.get("from_provider", ""), data.get("to_provider", ""))
                    elif name == "final_provider":
                        active_provider = data.get("provider", "unknown")
            success = True
        except ProviderError as exc:
            yield events.error_event(exc.message)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            yield events.error_event(str(exc))
            
        if active_provider == "unknown":
            try:
                candidates = resolver.pick(model_id, user_id=user_id)
                if candidates:
                    active_provider = candidates[0][4]
            except Exception:
                pass
                
        yield events.done_event(via_provider=active_provider)

        # 4. If persistent and stream succeeded, append user & assistant turns
        if req.conversation_id and success and user_msg_dict and assistant_text:
            assistant_msg_dict = {"role": "assistant", "content": assistant_text}
            meta = await run_in_threadpool(
                _persist_turn,
                drive,
                req.conversation_id,
                user_id,
                [user_msg_dict, assistant_msg_dict],
            )
            if meta:
                msg_count = meta.get("message_count", 0)
                if meta.get("title") == "New Chat" and msg_count == 2:
                    background_tasks.add_task(
                        auto_title_background_task,
                        req.conversation_id,
                        user_msg_dict["content"],
                        resolver,
                        rate_limiter,
                        user_id,
                    )
                if msg_count >= 20 and msg_count % 20 == 0:
                    background_tasks.add_task(
                        summarize_conversation_task,
                        req.conversation_id,
                        resolver,
                        rate_limiter,
                        user_id,
                    )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
