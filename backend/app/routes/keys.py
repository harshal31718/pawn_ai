"""BYOK provider API key routes.

All routes are auth-protected by AuthMiddleware (request.state.user_id is set).
Keys are stored encrypted (AES-256-GCM) in Supabase and are never returned to
the client — GET /keys returns only the list of providers a user has configured.
"""

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.core import key_store

router = APIRouter(prefix="/keys", tags=["keys"])


class KeyUpdate(BaseModel):
    api_key: str


@router.get("")
async def list_keys(request: Request):
    """Return the list of providers this user has a key configured for."""
    user_id = request.state.user_id
    return {"providers": key_store.list_providers(user_id)}


@router.put("/{provider}")
async def set_key(provider: str, req: KeyUpdate, request: Request):
    """Encrypt and store the user's API key for a provider."""
    user_id = request.state.user_id
    if provider not in key_store.VALID_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown provider: '{provider}'.",
        )
    if not req.api_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="API key cannot be empty.",
        )
    key_store.set_key(user_id, provider, req.api_key.strip())
    return {"status": "ok", "provider": provider}


@router.delete("/{provider}")
async def delete_key(provider: str, request: Request):
    """Delete the user's API key for a provider."""
    user_id = request.state.user_id
    if provider not in key_store.VALID_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown provider: '{provider}'.",
        )
    key_store.delete_key(user_id, provider)
    return {"status": "ok", "provider": provider}
