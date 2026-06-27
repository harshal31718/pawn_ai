"""JWT creation and validation for user sessions."""

from datetime import datetime, timedelta, timezone

import jwt

from app.config import JWT_SECRET

_ALGORITHM = "HS256"
_EXPIRY_DAYS = 7


def create_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(days=_EXPIRY_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=_ALGORITHM)


def decode_token(token: str) -> dict:
    """Returns payload dict. Raises jwt.PyJWTError on invalid/expired token."""
    return jwt.decode(token, JWT_SECRET, algorithms=[_ALGORITHM])
