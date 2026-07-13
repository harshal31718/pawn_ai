from typing import Optional
from starlette.concurrency import run_in_threadpool
from app.core.normalize import chat_stream
from app.core.drive_factory import call_drive, require_drive_for_user
from app.exceptions import NotConfiguredError
from app.storage import conversations_drive
from app.resolver.resolver import Resolver
from app.core.rate_limiter import EndpointRateLimiter

class DummyRateLimiter:
    def can_use(self, endpoint) -> bool: return True
    def record_call(self, endpoint_id, token_count=0): pass
    def record_429(self, endpoint_id, retry_after=60): pass
    def record_connect_failure(self, endpoint_id): pass
    def record_success(self, endpoint_id): pass

class DummyResolver:
    def pick(self, model_id, user_id=None):
        return [("https://api.google.com", "gemini-2.5-flash", {}, "ep-dummy", "google")]
    def pick_by_capability(self, level, visibility="internal"):
        return [("https://api.google.com", "gemini-2.5-flash", {}, "ep-dummy", "google")]
    def pick_model_by_capability(self, level, visibility="internal"):
        return "gemini-2.5-flash"

async def summarize_history(
    messages: list[dict],
    resolver: Optional[Resolver] = None,
    rate_limiter: Optional[EndpointRateLimiter] = None,
    user_id: Optional[str] = None,
) -> str:
    """
    Generates a concise bullet-point summary of the messages list using the fastest available model.
    """
    history_text = ""
    for m in messages:
        history_text += f"{m['role']}: {m['content']}\n"
        
    system_prompt = (
        "You are a helpful assistant. Write a concise bullet-point summary (maximum 150 words) "
        "of the following conversation. Capture only key facts, user preferences, and decisions. "
        "Return ONLY the plain markdown summary, no quote marks, no preamble, no commentary."
    )
    
    msgs = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": history_text}
    ]
    
    if resolver is None or rate_limiter is None:
        resolver = resolver or DummyResolver()
        rate_limiter = rate_limiter or DummyRateLimiter()
        
    try:
        model_id = resolver.pick_model_by_capability("fast")
        summary_text = ""
        async for token in chat_stream(model_id, msgs, resolver, rate_limiter, user_id=user_id):
            summary_text += token
        cleaned = summary_text.strip()
        if cleaned:
            return cleaned
    except Exception:
        pass
    return ""

async def summarize_conversation_task(
    conv_id: str,
    resolver: Optional[Resolver] = None,
    rate_limiter: Optional[EndpointRateLimiter] = None,
    user_id: Optional[str] = None,
) -> None:
    """
    Loads all messages for the conversation, generates a summary, and writes it to disk.
    Ingests the summary into the memory vector index (RAG).

    Best-effort background task: if Drive isn't available for this user, it
    silently skips (no local fallback — Drive is the only conversation store).
    """
    if not user_id:
        return
    try:
        drive = await run_in_threadpool(require_drive_for_user, user_id)
        messages = await run_in_threadpool(call_drive, conversations_drive.load_messages, drive, conv_id)
    except NotConfiguredError:
        return
    if not messages:
        return

    summary = await summarize_history(messages, resolver, rate_limiter, user_id=user_id)
    if summary:
        try:
            await run_in_threadpool(call_drive, conversations_drive.save_summary, drive, conv_id, summary)
        except NotConfiguredError:
            return

        if user_id:
            try:
                from app.memory.indexer import index_turn_task

                # Route the rolling summary through the same chunk/scope/write
                # path as a real turn (Phase M, M.3) -- chunked, appended to
                # this chat's own rag_chunks.jsonl, embedded, and written into
                # Postgres under the chat's current scope.
                await index_turn_task(
                    user_id, conv_id, None, [{"role": "assistant", "content": summary}]
                )
            except Exception as e:
                # Deliberately broad: this is a best-effort background task with
                # no HTTP response to attach an error to (index_turn_task already
                # handles its own expected failure modes internally, e.g.
                # NotConfiguredError -> silent return); this is a last-resort
                # safety net, not routes-layer error handling.
                import sys
                print(f"Failed to index summary for RAG: {e}", file=sys.stderr)
