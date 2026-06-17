import os
import httpx
from app.config import GEMINI_API_KEY

EMBED_BACKEND = os.getenv("PAWN_EMBED_BACKEND", "gemini")
OLLAMA_URL = os.getenv("PAWN_OLLAMA_URL", "http://localhost:11434")

async def _gemini_embed(text: str) -> list[float]:
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not configured.")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key={GEMINI_API_KEY}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            url,
            json={
                "model": "models/text-embedding-004",
                "content": {
                    "parts": [{"text": text}]
                }
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

async def embed(text: str) -> list[float]:
    """
    Retrieves 768-dimensional embedding vector for the given text.
    """
    if EMBED_BACKEND == "gemini":
        try:
            return await _gemini_embed(text)
        except Exception as e:
            if os.getenv("PAWN_EMBED_FALLBACK_TO_OLLAMA") == "true":
                return await _ollama_embed(text)
            raise e
    else:
        return await _ollama_embed(text)
