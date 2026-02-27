from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from typing import Optional

from backend.config import CONFIG_DIR

PBKDF2_ITERATIONS = 600_000
SALT_BYTES = 16
KEY_BYTES = 32
NONCE_BYTES = 12
SYNC_SALT_PATH = os.path.join(CONFIG_DIR, "sync_salt.bin")


def _get_aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except Exception as e:
        raise RuntimeError(
            "Missing dependency 'cryptography' required for E2E sync encryption."
        ) from e
    return AESGCM


def get_or_create_sync_salt() -> bytes:
    if os.path.exists(SYNC_SALT_PATH):
        with open(SYNC_SALT_PATH, "rb") as f:
            value = f.read()
            if len(value) >= SALT_BYTES:
                return value[:SALT_BYTES]
    salt = secrets.token_bytes(SALT_BYTES)
    with open(SYNC_SALT_PATH, "wb") as f:
        f.write(salt)
    return salt


def derive_key_from_passphrase(passphrase: str, salt: Optional[bytes] = None) -> bytes:
    if not passphrase or len(passphrase) < 8:
        raise ValueError("Passphrase must be at least 8 characters")
    use_salt = salt or get_or_create_sync_salt()
    return hashlib.pbkdf2_hmac(
        "sha256",
        passphrase.encode("utf-8"),
        use_salt,
        PBKDF2_ITERATIONS,
        dklen=KEY_BYTES,
    )


def encrypt_snapshot(plaintext: bytes, key: bytes, metadata: Optional[dict] = None) -> dict:
    AESGCM = _get_aesgcm()
    aesgcm = AESGCM(key)
    nonce = secrets.token_bytes(NONCE_BYTES)
    aad = json.dumps(metadata or {}, sort_keys=True).encode("utf-8")
    ciphertext = aesgcm.encrypt(nonce, plaintext, aad)
    checksum = hashlib.sha256(ciphertext).hexdigest()
    return {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "checksum_sha256": checksum,
        "nonce_b64": base64.b64encode(nonce).decode("ascii"),
        "ciphertext_b64": base64.b64encode(ciphertext).decode("ascii"),
    }


def decrypt_snapshot(payload: dict, key: bytes, metadata: Optional[dict] = None) -> bytes:
    AESGCM = _get_aesgcm()
    aesgcm = AESGCM(key)
    nonce = base64.b64decode(payload["nonce_b64"])
    ciphertext = base64.b64decode(payload["ciphertext_b64"])
    aad = json.dumps(metadata or {}, sort_keys=True).encode("utf-8")
    return aesgcm.decrypt(nonce, ciphertext, aad)
