"""AES-256-GCM encryption for BYOK API keys and Google Drive tokens.

Format: base64(nonce[12] + ciphertext + tag[16])
Key: derived from ENCRYPTION_SECRET (32-byte hex string → 32 raw bytes).
"""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import ENCRYPTION_SECRET


def _key() -> bytes:
    if not ENCRYPTION_SECRET:
        raise RuntimeError("ENCRYPTION_SECRET not configured")
    raw = bytes.fromhex(ENCRYPTION_SECRET)
    if len(raw) != 32:
        raise RuntimeError("ENCRYPTION_SECRET must be a 32-byte (64-char) hex string")
    return raw


def encrypt(plain: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_key()).encrypt(nonce, plain.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def decrypt(cipher: str) -> str:
    data = base64.b64decode(cipher)
    nonce, ct = data[:12], data[12:]
    return AESGCM(_key()).decrypt(nonce, ct, None).decode()
