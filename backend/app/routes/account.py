"""Login-change plan (2026-07-23): authenticated account-settings routes.

Behind AuthMiddleware (not under /auth/, which is deliberately public) --
request.state.user_id is already set, no manual token decoding needed,
mirroring routes/keys.py's pattern.
"""
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.core.password_utils import hash_password
from app.db.postgres_client import execute

router = APIRouter(prefix="/account", tags=["account"])

MIN_PASSWORD_LENGTH = 8


class ChangePasswordRequest(BaseModel):
    new_password: str


@router.put("/password")
async def change_password(req: ChangePasswordRequest, request: Request):
    """Set a new password for the already-authenticated caller. No current-
    password check -- the active session is the authentication, so this
    doubles as both "change" (know the old one, don't care) and "forgot"
    (don't remember it, doesn't matter) from within Settings."""
    user_id = request.state.user_id

    if len(req.new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"New password must be at least {MIN_PASSWORD_LENGTH} characters.",
        )

    execute(
        "update users set password_hash = %s, password_changed = true where user_id = %s",
        (hash_password(req.new_password), user_id),
    )
    return {"status": "ok"}
