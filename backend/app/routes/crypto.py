"""Crypto salt route.

The frontend derives its AES-256-GCM key from the user's passphrase and a
PBKDF2 salt. The salt is *not secret* (PBKDF2 salts never are) but it must be
stable across sessions, so it is stored once per user and returned on request,
as ``PAWN/.salt`` on the user's Google Drive — Drive is the only storage
backend for user data, no local fallback (see core/drive_factory.py).

The salt is created (16 random bytes, base64-encoded) on first request and is
idempotent thereafter. The backend never sees the passphrase or the derived
key — only this public salt and, elsewhere, opaque ciphertext blobs.
"""

import base64
import os

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool

from app.core.drive_factory import call_drive, require_drive_for_user

router = APIRouter(prefix="/crypto", tags=["crypto"])

_SALT_FILENAME = ".salt"
_SALT_BYTES = 16


def _new_salt_b64() -> str:
    return base64.b64encode(os.urandom(_SALT_BYTES)).decode("ascii")


def _drive_get_or_create_salt(drive) -> str:
    root = drive.get_or_create_root()
    existing = drive.download_text_by_name(_SALT_FILENAME, root)
    if existing and existing.strip():
        return existing.strip()
    salt = _new_salt_b64()
    drive.upload_text(_SALT_FILENAME, salt, root)
    return salt


@router.get("/salt")
async def get_salt(request: Request):
    """Return this user's PBKDF2 salt (base64), creating it on first request."""
    user_id = request.state.user_id
    drive = await run_in_threadpool(require_drive_for_user, user_id)
    salt = await run_in_threadpool(call_drive, _drive_get_or_create_salt, drive)
    return {"salt": salt}
