"""BYOK provider API key routes.

All routes are auth-protected by AuthMiddleware (request.state.user_id is set).
Keys are stored encrypted (AES-256-GCM) in Postgres and are never returned to
the client — GET /keys returns only the list of providers a user has configured.
"""

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.core import key_store

router = APIRouter(prefix="/keys", tags=["keys"])


class KeyUpdate(BaseModel):
    api_key: str


class KaggleConfigUpdate(BaseModel):
    username: str
    api_token: str


@router.get("")
async def list_keys(request: Request):
    """Return the list of providers this user has a key configured for."""
    user_id = request.state.user_id
    return {"providers": key_store.list_providers(user_id)}


# --- Kaggle config (dict payload) -------------------------------------------
# Declared BEFORE the generic /{provider} routes so "kaggle" matches these and
# not the single-string-key handlers. Token values are never returned.


@router.get("/kaggle")
async def get_kaggle_config(request: Request):
    """Return Kaggle config shape only (never the token)."""
    user_id = request.state.user_id
    cfg = key_store.get_kaggle(user_id)
    if not cfg:
        return {"has_creds": False, "kernels": {}}
    return {
        "has_creds": bool(cfg.get("username") and cfg.get("api_token")),
        "kernels": cfg.get("kernels", {}),
    }


@router.put("/kaggle")
async def set_kaggle_config(req: KaggleConfigUpdate, request: Request):
    """Store the user's Kaggle username + API token (encrypted)."""
    user_id = request.state.user_id
    if not req.username.strip() or not req.api_token.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both username and API token are required.",
        )
    key_store.set_kaggle(
        user_id,
        {"username": req.username.strip(), "api_token": req.api_token.strip()},
    )
    return {"status": "ok"}


@router.delete("/kaggle")
async def delete_kaggle_config(request: Request):
    """Delete the user's Kaggle config."""
    user_id = request.state.user_id
    key_store.delete_kaggle(user_id)
    return {"status": "ok"}


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
