from typing import Literal
from fastapi import APIRouter, HTTPException, status, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.core.normalize import chat_stream
from app.resolver.resolver import Resolver
from app.core.rate_limiter import EndpointRateLimiter
from app.exceptions import NotConfiguredError, ProviderError, NoEndpointError
from app import events
from app.constants import TRACE_MAX_ENTRIES
from app.core import key_store
from app.core.drive_factory import call_drive, require_drive_for_user
from app.storage import conversations_drive
from app.memory.summarize import summarize_conversation_task
from app.memory.indexer import index_turn_task, resolve_scope

router = APIRouter()


def _load_conversation_bundle(drive, conv_id: str, user_id: str | None):
    """Blocking: load (meta, history, summary) for an existing conversation in one
    threadpool hop. Returns (None, [], None) when the conversation doesn't exist."""
    meta = conversations_drive.get_conversation_meta(drive, conv_id)
    if not meta:
        return None, [], None
    history = conversations_drive.load_messages(drive, conv_id)
    summary = conversations_drive.load_summary(drive, conv_id)
    return meta, history, summary


def _persist_turn(drive, conv_id: str, user_id: str | None, turns: list[dict]):
    """Blocking: append the user+assistant turns and return the refreshed meta."""
    conversations_drive.append_messages(drive, conv_id, turns)
    return conversations_drive.get_conversation_meta(drive, conv_id)


def _build_trace(tool_log: list[dict], citations: list[dict]) -> list[dict]:
    """Phase A / A.8: flattens AgentState.tool_log/citations (as left in the
    graph's final checkpointed state) into the persisted `trace` shape --
    `{kind, agent, ...payload}` -- capped to TRACE_MAX_ENTRIES (oldest first
    dropped). Tool entries (including nested subagent ones, already tagged
    `agent` by execute_node/run_subagent) come first in execution order, then
    citations -- citations are always treated as "newer" than tool entries by
    the cap regardless of when each was actually found mid-run (a citation
    discovered by the very first tool call still survives a truncation that
    drops early tool entries); this loses cross-kind chronological ordering
    once the cap kicks in, accepted as a minor, documented tradeoff. Empty
    input -> empty trace, so the direct-answer fast path (tool_log/citations
    never populated) attaches no trace field at all."""
    trace = [
        {
            "kind": "tool",
            "agent": entry.get("agent", "main"),
            "name": entry.get("name", ""),
            "args": entry.get("args", {}),
            "observation": entry.get("observation", ""),
            "elapsed_ms": entry.get("elapsed_ms", 0),
        }
        for entry in tool_log
    ]
    trace.extend(
        {"kind": "citation", "agent": "main", "url": c.get("url", ""), "title": c.get("title", "")}
        for c in citations
    )
    return trace[-TRACE_MAX_ENTRIES:]


def _prior_turn_used_tools(history: list[dict]) -> bool:
    """Router heavy-trigger (A.5): True when the most recent persisted
    assistant message carries a trace with at least one tool entry (A.8) —
    i.e. the previous turn actually used tools."""
    for past in reversed(history):
        if past.get("role") == "assistant":
            return any(entry.get("kind") == "tool" for entry in (past.get("trace") or []))
    return False


def _create_with_id(drive, conv_id: str, user_id: str | None, model_id: str):
    """Blocking: materialize a client-owned conversation id (lazy-create on first message)."""
    return conversations_drive.create_conversation(
        drive, user_id=user_id, conv_id=conv_id, title="New Chat", model_id=model_id
    )

class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str

class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    model_id: str | None = None        # Canonical model ID (e.g. "gemini-2.5-flash", "llama-3.3-70b")
    provider: str | None = None        # Backward compatibility for provider selection
    doc_id: str | None = None          # deprecated/unused — doc content now reaches the model only via the doc_search tool (Phase A / A.4); kept for frontend backward-compat, ignored here
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
    """Background task to generate and save the conversation title.

    Best-effort: if Drive isn't available for this user, it silently skips
    (no local fallback — Drive is the only conversation store)."""
    if not user_id:
        return
    title = await generate_title(first_prompt, resolver, rate_limiter, user_id=user_id)
    try:
        drive = await run_in_threadpool(require_drive_for_user, user_id)
        await run_in_threadpool(call_drive, conversations_drive.update_conversation_title, drive, conv_id, title)
    except NotConfiguredError:
        return

@router.post("/chat")
async def chat(req: ChatRequest, request: Request, background_tasks: BackgroundTasks):
    user_msg_dict = None
    user_id = request.state.user_id
    resolver = request.app.state.resolver
    rate_limiter = request.app.state.rate_limiter
    # Blocking I/O (Postgres/Drive) is run off the event loop so a slow backend
    # can't stall every other in-flight request. Drive is only required for
    # persistence — a stateless one-off message needs neither. `doc_id` no
    # longer triggers a Drive load here: a document's content is indexed once
    # at upload time (routes/upload.py) and reached only via the doc_search
    # tool, never injected into this request's context.
    needs_drive = bool(req.conversation_id)
    drive = await run_in_threadpool(require_drive_for_user, user_id) if needs_drive else None
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
    # Router heavy-trigger (A.5): did the previous assistant turn use tools?
    # Derived from the last persisted assistant message's trace (A.8) below.
    prior_turn_used_tools = False
    if req.conversation_id:
        meta, history, summary = await run_in_threadpool(
            call_drive, _load_conversation_bundle, drive, req.conversation_id, user_id
        )
        prior_turn_used_tools = _prior_turn_used_tools(history)
        if not meta:
            # The client owns the conversation id (optimistic UI). If the background
            # create op hasn't landed yet, materialize it now so the first message
            # is never lost to a 404 — the flow stays fail-proof.
            await run_in_threadpool(call_drive, _create_with_id, drive, req.conversation_id, user_id, model_id)
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

    # 2. doc_id (if present) only records that a document is attached to this
    # chat's scope — its content reaches the model exclusively via the
    # doc_search tool (Phase A / A.4), never injected into context here.

    # 3. Resolve this chat's current scope (Phase M) once per request, so the
    # agent's search_memory action queries the right RAG scope. Stateless
    # chats (no conversation_id) get scope_type/scope_id = None -- the agent
    # never queries memory for them.
    scope_type = None
    scope_id = None
    if req.conversation_id:
        try:
            scope = await run_in_threadpool(resolve_scope, user_id, req.conversation_id, drive)
        except NotConfiguredError:
            scope = None
        if scope:
            scope_type, scope_id = scope

    # 4. Build inputs and config for LangGraph Agent (graph v2 AgentState, A.6)
    inputs = {
        "messages": messages_to_send,
        "user_id": user_id,
        "conversation_id": req.conversation_id or "stateless",
        "user_model_id": model_id,
        "has_doc": bool(req.doc_id),
        "has_tools_likely": prior_turn_used_tools,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "difficulty": "light",
        "needs_agent": False,
        "plan": [],
        "tool_log": [],
        "tokens_used": 0,
        "citations": [],
        "final_answer": None,
        "revision_count": 0,
        "needs_revision": False,
        "verify_draft": None,
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
                        yield events.step_event(data.get("label", ""), data.get("detail", ""), data.get("agent", "main"))
                    elif name == "memory_hit":
                        yield events.memory_hit_event(
                            data.get("summary", ""), data.get("scope", ""), data.get("source_conv_id", "")
                        )
                    elif name == "model_call":
                        yield events.model_call_event(data.get("model", ""), data.get("purpose", ""))
                    elif name == "provider_switch":
                        yield events.provider_switch_event(data.get("from_provider", ""), data.get("to_provider", ""))
                    elif name == "citation":
                        yield events.citation_event(data.get("url", ""), data.get("title", ""))
                    elif name == "final_provider":
                        active_provider = data.get("provider", "unknown")
            success = True
        except ProviderError as exc:
            yield events.error_event(exc.message)
        except NoEndpointError:
            # Genuine full exhaustion: chat_stream already fails over across
            # every endpoint of every fallback model for this role (see
            # normalize.chat_stream/resolver.fallback_models) before raising
            # this -- so if it still escapes, there really is nothing left to
            # try, not a bug. Distinct from the generic catch-all below so the
            # user gets an honest message instead of "unexpected error" (F-1,
            # 2026-07-14 -- this used to fall through to the generic handler
            # because NoEndpointError isn't a ProviderError subclass).
            yield events.error_event(
                "All available models are currently rate-limited. Please try again in a moment."
            )
        except Exception:
            import traceback
            traceback.print_exc()
            yield events.error_event("An unexpected error occurred while generating the response.")
            
        if active_provider == "unknown":
            try:
                candidates = resolver.pick(model_id, user_id=user_id)
                if candidates:
                    active_provider = candidates[0][4]
            except Exception:
                pass
                
        yield events.done_event(via_provider=active_provider)

        # 4. If persistent and stream succeeded, append user & assistant turns.
        # This runs after done_event was already sent — the user has already
        # seen the reply, so a Drive failure here is logged, not surfaced.
        if req.conversation_id and success and user_msg_dict and assistant_text:
            assistant_msg_dict = {"role": "assistant", "content": assistant_text}
            # Phase A / A.8: pull the graph's final checkpointed tool_log/citations
            # for this run and attach them as `trace` -- absent (not just empty)
            # when there's nothing to show, e.g. the direct-answer fast path.
            try:
                snapshot = await graph.aget_state(config)
                state_values = snapshot.values if snapshot else {}
            except Exception as exc:
                import sys
                print(f"Failed to read agent state for trace persistence on {req.conversation_id}: {exc}", file=sys.stderr)
                state_values = {}
            citations = state_values.get("citations", [])
            trace = _build_trace(state_values.get("tool_log", []), citations)
            if trace:
                assistant_msg_dict["trace"] = trace
            # citations is also persisted as its own top-level field (not just
            # folded into `trace`) -- the frontend's Citation chips read
            # message.citations directly, never derived from trace entries.
            if citations:
                assistant_msg_dict["citations"] = citations
            try:
                meta = await run_in_threadpool(
                    call_drive,
                    _persist_turn,
                    drive,
                    req.conversation_id,
                    user_id,
                    [user_msg_dict, assistant_msg_dict],
                )
            except NotConfiguredError as exc:
                import sys
                print(f"Failed to persist chat turn for {req.conversation_id}: {exc}", file=sys.stderr)
                meta = None
            if meta:
                background_tasks.add_task(
                    index_turn_task,
                    user_id,
                    req.conversation_id,
                    None,
                    [user_msg_dict, assistant_msg_dict],
                )
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
