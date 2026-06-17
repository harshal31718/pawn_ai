from typing import Optional
from app.core.normalize import chat_stream
from app.storage import conversations as storage
from app.resolver.resolver import Resolver
from app.core.rate_limiter import EndpointRateLimiter

class DummyRateLimiter:
    def can_use(self, endpoint) -> bool: return True
    def record_call(self, endpoint_id, token_count=0): pass
    def record_429(self, endpoint_id, retry_after=60): pass
    def record_connect_failure(self, endpoint_id): pass
    def record_success(self, endpoint_id): pass

class DummyResolver:
    def pick(self, model_id):
        return [("https://api.google.com", "gemini-2.5-flash", {}, "ep-dummy", "google")]
    def pick_by_capability(self, level, visibility="internal"):
        return [("https://api.google.com", "gemini-2.5-flash", {}, "ep-dummy", "google")]
    def pick_model_by_capability(self, level, visibility="internal"):
        return "gemini-2.5-flash"

async def summarize_history(
    messages: list[dict],
    resolver: Optional[Resolver] = None,
    rate_limiter: Optional[EndpointRateLimiter] = None,
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
        async for token in chat_stream(model_id, msgs, resolver, rate_limiter):
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
) -> None:
    """
    Loads all messages for the conversation, generates a summary, and writes it to disk.
    Ingests the summary into the memory vector index (RAG).
    """
    messages = storage.load_messages(conv_id)
    if not messages:
        return
    
    summary = await summarize_history(messages, resolver, rate_limiter)
    if summary:
        storage.save_summary(conv_id, summary)
        
        try:
            from app.memory.embed import embed
            from app.memory.index import add_chunk
            
            embedding = await embed(summary)
            add_chunk(conv_id, summary, embedding)
        except Exception as e:
            import sys
            print(f"Failed to index summary for RAG: {e}", file=sys.stderr)
