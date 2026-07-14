import os
import httpx

EMBED_BACKEND = os.getenv("PAWN_EMBED_BACKEND", "gemini")
OLLAMA_URL = os.getenv("PAWN_OLLAMA_URL", "http://localhost:11434")


def _resolve_gemini_key(user_id: str | None) -> str:
    """Return the user's Google BYOK key (from Settings), or "" if none."""
    if not user_id:
        return ""
    from app.core import key_store
    return key_store.get_key(user_id, "google") or ""


async def _gemini_embed(text: str, api_key: str) -> list[float]:
    if not api_key:
        raise ValueError("No Google API key configured for embeddings.")
    # text-embedding-004 was shut down by Google 2026-01-14 (gemini-embedding-001
    # follows 2026-07-14) -- gemini-embedding-2 is the current model. It defaults
    # to 3072-dim output but supports the Matryoshka-truncated 768 the schema
    # expects (a Google-recommended dimension, auto-normalized) via
    # output_dimensionality. See plan_memory_scoping.md M.1.
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:embedContent?key={api_key}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            url,
            json={
                "model": "models/gemini-embedding-2",
                "content": {
                    "parts": [{"text": text}]
                },
                "outputDimensionality": 768,
            },
            headers={"Content-Type": "application/json"}
        )
        if resp.status_code != 200:
            raise Exception(f"Gemini embedding API failed with status {resp.status_code}: {resp.text}")
        data = resp.json()
        return data["embedding"]["values"]

async def _ollama_embed(text: str) -> list[float]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={
                "model": "nomic-embed-text",
                "prompt": text
            }
        )
        if resp.status_code != 200:
            raise Exception(f"Ollama embedding API failed with status {resp.status_code}: {resp.text}")
        data = resp.json()
        return data["embedding"]

async def embed(text: str, user_id: str | None = None) -> list[float]:
    """
    Retrieves 768-dimensional embedding vector for the given text.

    Uses the user's Google BYOK key (configured in Settings) for the Gemini
    backend. Raises if no key is configured, unless Ollama fallback is enabled.
    """
    if EMBED_BACKEND == "gemini":
        try:
            api_key = _resolve_gemini_key(user_id)
            return await _gemini_embed(text, api_key)
        except Exception as e:
            if os.getenv("PAWN_EMBED_FALLBACK_TO_OLLAMA") == "true":
                return await _ollama_embed(text)
            raise e
    else:
        return await _ollama_embed(text)
