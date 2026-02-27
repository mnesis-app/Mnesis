import importlib.util

import pytest

from backend.sync import crypto


def test_derive_key_requires_min_passphrase_length():
    with pytest.raises(ValueError):
        crypto.derive_key_from_passphrase("short", salt=b"0123456789abcdef")


def test_derive_key_length_is_32_bytes():
    key = crypto.derive_key_from_passphrase("correct horse battery", salt=b"0123456789abcdef")
    assert isinstance(key, bytes)
    assert len(key) == 32


@pytest.mark.skipif(importlib.util.find_spec("cryptography") is None, reason="cryptography not installed")
def test_encrypt_decrypt_roundtrip_with_metadata():
    key = crypto.derive_key_from_passphrase("correct horse battery", salt=b"0123456789abcdef")
    plaintext = b"snapshot-bytes"
    metadata = {"created_at": "2026-02-19T00:00:00+00:00", "device_id": "device-a"}

    encrypted = crypto.encrypt_snapshot(plaintext, key, metadata=metadata)
    assert encrypted["version"] == 1
    assert encrypted["checksum_sha256"]

    decrypted = crypto.decrypt_snapshot(encrypted, key, metadata=metadata)
    assert decrypted == plaintext
