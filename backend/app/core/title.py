"""Deriving a default conversation title directly from the first user prompt --
no model call, so it never fails/costs tokens/depends on a configured key. Used
as the instant default when a chat is created, and as generate_title's fallback
if the LLM-based title call in routes/chat.py errors or comes back empty."""

import re

TITLE_MAX_CHARS = 40


def derive_fallback_title(first_prompt: str) -> str:
    """Collapses whitespace and truncates to TITLE_MAX_CHARS at a word
    boundary (never mid-word), appending an ellipsis if truncated. Returns
    "New Chat" only if the prompt is empty/whitespace-only."""
    cleaned = re.sub(r"\s+", " ", first_prompt).strip()
    if not cleaned:
        return "New Chat"
    if len(cleaned) <= TITLE_MAX_CHARS:
        return cleaned
    truncated = cleaned[:TITLE_MAX_CHARS]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]
    return truncated.rstrip() + "…"
