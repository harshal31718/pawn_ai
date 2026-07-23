"""Login-change plan (2026-07-23): authenticated account-settings routes.

Behind AuthMiddleware (not under /auth/, which is deliberately public) --
request.state.user_id is already set, no manual token decoding needed,
mirroring routes/keys.py's pattern.
"""
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.core.password_utils import hash_password, verify_password
from app.db.postgres_client import execute, fetchone

router = APIRouter(prefix="/account", tags=["account"])

MIN_PASSWORD_LENGTH = 8


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.put("/password")
async def change_password(req: ChangePasswordRequest, request: Request):
    """Verify the caller's current password, then replace it and mark
    password_changed -- this is what stops PasswordNudgeModal reappearing."""
    user_id = request.state.user_id

    row = fetchone("select password_hash from users where user_id = %s", (user_id,))
    if not row or not row.get("password_hash") or not verify_password(
        req.current_password, row["password_hash"]
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Current password is incorrect.")

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
