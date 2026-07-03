"""Crypto salt route.

The frontend derives its AES-256-GCM key from the user's passphrase and a
PBKDF2 salt. The salt is *not secret* (PBKDF2 salts never are) but it must be
stable across sessions, so it is stored once per user and returned on request.

Storage location:
  - If the user has Google Drive linked: ``PAWN/.salt`` on their Drive.
  - Otherwise (local-only fallback): ``<DATA_DIR>/salts/<user_id>.salt``.

The salt is created (16 random bytes, base64-encoded) on first request and is
idempotent thereafter. The backend never sees the passphrase or the derived
key — only this public salt and, elsewhere, opaque ciphertext blobs.
"""

import base64
import os

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool

from app.constants import DATA_DIR
from app.core.drive_factory import get_drive_for_user

router = APIRouter(prefix="/crypto", tags=["crypto"])

_SALT_FILENAME = ".salt"
_SALT_BYTES = 16
_LOCAL_SALT_DIR = DATA_DIR / "salts"


def _new_salt_b64() -> str:
    return base64.b64encode(os.urandom(_SALT_BYTES)).decode("ascii")


def _local_get_or_create_salt(user_id: str) -> str:
    _LOCAL_SALT_DIR.mkdir(parents=True, exist_ok=True)
    # user_id is a server-issued UUID, but sanitize defensively against traversal.
    safe = "".join(c for c in user_id if c.isalnum() or c in ("-", "_"))
    path = _LOCAL_SALT_DIR / f"{safe}{_SALT_FILENAME}"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    salt = _new_salt_b64()
    path.write_text(salt, encoding="utf-8")
    return salt


def _drive_get_or_create_salt(drive, user_id: str) -> str:
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
    drive = get_drive_for_user(user_id)
    if drive is not None:
        salt = await run_in_threadpool(_drive_get_or_create_salt, drive, user_id)
    else:
        salt = await run_in_threadpool(_local_get_or_create_salt, user_id)
    return {"salt": salt}
