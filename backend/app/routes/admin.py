"""PAWN 2.0 Phase B.5: admin routes.

Every route here is gated by `Depends(require_admin)` -- a non-admin gets a
403 regardless of frontend nav gating (which is UX only, see AdminPage.tsx).
Pool keys are never returned in plaintext to any client, admin included --
only "configured: true/false" + enabled/saturation metadata.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core import pool_key_store
from app.core.admin import require_admin
from app.db.postgres_client import fetchone

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


class PoolKeyUpdate(BaseModel):
    api_key: str


class PoolKeyPatch(BaseModel):
    enabled: bool | None = None
    saturation_pct: int | None = None


@router.get("/pool-keys")
async def list_pool_keys():
    """Every configured pool provider's metadata (never the key itself)."""
    rows = pool_key_store.list_pool_providers()
    return {
        "providers": [
            {
                "provider": row["provider"],
                "configured": True,
                "enabled": row["enabled"],
                "saturation_pct": row["saturation_pct"],
            }
            for row in rows
        ]
    }


@router.put("/pool-keys/{provider}")
async def set_pool_key(provider: str, req: PoolKeyUpdate):
    """Encrypt and store (or replace) the operator's shared key for a provider."""
    if provider not in pool_key_store.POOL_VALID_PROVIDERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown provider: '{provider}'.")
    if not req.api_key.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "API key cannot be empty.")
    pool_key_store.set_pool_key(provider, req.api_key.strip())
    return {"status": "ok", "provider": provider}


@router.delete("/pool-keys/{provider}")
async def delete_pool_key(provider: str):
    if provider not in pool_key_store.POOL_VALID_PROVIDERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown provider: '{provider}'.")
    pool_key_store.delete_pool_key(provider)
    return {"status": "ok", "provider": provider}


@router.patch("/pool-keys/{provider}")
async def patch_pool_key(provider: str, req: PoolKeyPatch):
    """Enable/disable a provider's pool key and/or override its saturation
    threshold (Phase C). Both fields optional -- only the ones present are
    changed."""
    if provider not in pool_key_store.POOL_VALID_PROVIDERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown provider: '{provider}'.")
    if pool_key_store.get_pool_config(provider) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No pool key configured for '{provider}'.")
    if req.enabled is not None:
        pool_key_store.set_enabled(provider, req.enabled)
    if req.saturation_pct is not None:
        pool_key_store.set_saturation_pct(provider, req.saturation_pct)
    return {"status": "ok", "provider": provider}


@router.get("/stats")
async def get_stats():
    """Registered-user count N (Phase C's fair-share denominator) -- from the
    main app DB, not the shared keys DB (this deployment's own user count,
    not whatever users happen to exist in a shared-keys Postgres)."""
    row = fetchone("select count(*) as n from users")
    n = row["n"] if row else 0
    return {"registered_users": n}
