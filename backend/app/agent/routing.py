from app.config import GROQ_API_KEY, CEREBRAS_API_KEY

PURPOSE_TO_LEVEL = {
    "plan":     "fast",      # Low-cost planning; quick, high-quota models
    "draft":    "balanced",  # Most sub-task work; solid quality
    "critique": "balanced",  # Second opinion
    "research": "research",  # Deep reasoning
}

def resolve_level(level: str, purpose: str | None = None) -> tuple[str, str | None]:
    """
    Temporary resolution mapping capability levels to specific providers/models
    prior to the Phase 1.6 registry-based resolver implementation.
    """
    if level == "fast":
        # Plan is fast, Gemini Flash is a solid default
        return "gemini", "gemini-2.5-flash"
    elif level == "balanced":
        # Draft vs Critique: try to vary the provider if keys allow
        if purpose == "critique":
            if CEREBRAS_API_KEY:
                return "cerebras", "llama-3.3-70b"
            if GROQ_API_KEY:
                return "groq", "llama-3.3-70b-versatile"
            return "gemini", "gemini-2.5-flash"
        else:
            if GROQ_API_KEY:
                return "groq", "llama-3.3-70b-versatile"
            if CEREBRAS_API_KEY:
                return "cerebras", "llama-3.3-70b"
            return "gemini", "gemini-2.5-flash"
    elif level == "research":
        # Research defaults to gemini-2.5-flash for now (no DeepSeek key yet)
        return "gemini", "gemini-2.5-flash"
    return "gemini", "gemini-2.5-flash"
