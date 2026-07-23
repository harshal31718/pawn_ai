"""PAWN 2.0 Phase B: admin role.

Single hardcoded admin email (app.constants.ADMIN_EMAIL) -- no schema/JWT
change needed for a one-operator deployment. request.state.email is already
set by app.middleware.auth.AuthMiddleware on every authenticated request.
"""
from fastapi import HTTPException, Request

from app.constants import ADMIN_EMAIL


def is_admin(email: str | None) -> bool:
    return bool(email) and email == ADMIN_EMAIL


def require_admin(request: Request) -> None:
    """FastAPI dependency: raises 403 unless the caller is the admin.

    Use as `Depends(require_admin)` on every admin route. Frontend nav gating
    (Sidebar's Admin entry) is UX only -- this is the real control.
    """
    if not is_admin(getattr(request.state, "email", None)):
        raise HTTPException(403, "Admin access required")
