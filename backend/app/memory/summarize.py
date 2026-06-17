from app.core.normalize import chat_stream, PROVIDERS
from app.storage import conversations as storage

async def summarize_history(messages: list[dict]) -> str:
    """
    Generates a concise bullet-point summary of the messages list using the fastest provider.
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
    
    for provider in ["groq", "cerebras", "gemini"]:
        if provider not in PROVIDERS:
            continue
        try:
            summary_text = ""
            async for token in chat_stream(provider, msgs):
                summary_text += token
            cleaned = summary_text.strip()
            if cleaned:
                return cleaned
        except Exception:
            continue
    return ""

async def summarize_conversation_task(conv_id: str) -> None:
    """
    Loads all messages for the conversation, generates a summary, and writes it to disk.
    """
    messages = storage.load_messages(conv_id)
    if not messages:
        return
    
    # Generate the summary
    summary = await summarize_history(messages)
    if summary:
        storage.save_summary(conv_id, summary)
