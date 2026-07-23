"""Login-change plan (2026-07-23): password generation + Argon2id hashing.

Distinct from core/crypto.py's AES-256-GCM (reversible symmetric encryption,
used for recoverable secrets like Drive tokens/BYOK keys) -- passwords must
never be recoverable, so this uses a one-way KDF instead.
"""
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError, VerifyMismatchError

import secrets as _secrets

# Excludes visually ambiguous characters (0/O, 1/l/I) -- this password is
# shown to the user exactly once (the signup reveal modal) and may be
# hand-copied, so ambiguity here means a real risk of a mistyped login.
_PASSWORD_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

_hasher = PasswordHasher()


def generate_password(length: int = 16) -> str:
    """Cryptographically random password for the one-time signup reveal."""
    return "".join(_secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))


def hash_password(password: str) -> str:
    """Argon2id hash (library defaults) -- includes its own salt, no
    separate salt storage/management needed."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """True if `password` matches `password_hash`, False on any mismatch or
    malformed-hash error -- never raises, so callers can treat this as a
    plain boolean check without their own try/except."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHash):
        return False
