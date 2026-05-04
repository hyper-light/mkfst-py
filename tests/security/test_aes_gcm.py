from __future__ import annotations

import secrets

import pytest

from mkfst.encryption import AESGCMFernet, EncryptionError
from mkfst.env import Env


def _env(secret: str | None = None) -> Env:
    return Env(MERCURY_SYNC_AUTH_SECRET=secret if secret is not None else "x" * 32)


def test_roundtrip_preserves_plaintext() -> None:
    fernet = AESGCMFernet(_env())
    pt = b"hello mkfst"
    ct = fernet.encrypt(pt)
    assert fernet.decrypt(ct) == pt


def test_each_call_uses_a_fresh_nonce() -> None:
    fernet = AESGCMFernet(_env())
    pt = b"deterministic input"
    a = fernet.encrypt(pt)
    b = fernet.encrypt(pt)
    assert a != b
    # Nonce lives at offset 1 (skip 1-byte version).
    assert a[1:13] != b[1:13]
    assert fernet.decrypt(a) == pt
    assert fernet.decrypt(b) == pt


def test_decrypt_with_two_distinct_secrets_fails() -> None:
    """Old implementation embedded the encryption key inside the ciphertext;
    any holder could decrypt. The fix derives the key from the configured
    secret only, so a second instance with a different secret must fail."""
    a = AESGCMFernet(_env("a-secret-with-enough-bytes-here!!"))
    b = AESGCMFernet(_env("a-DIFFERENT-secret-with-len>=16!!"))
    pt = b"top secret"
    ct = a.encrypt(pt)
    with pytest.raises(EncryptionError):
        b.decrypt(ct)


def test_tamper_with_ciphertext_fails() -> None:
    fernet = AESGCMFernet(_env())
    ct = bytearray(fernet.encrypt(b"sensitive payload"))
    ct[-1] ^= 0x01
    with pytest.raises(EncryptionError):
        fernet.decrypt(bytes(ct))


def test_tamper_with_nonce_fails() -> None:
    fernet = AESGCMFernet(_env())
    ct = bytearray(fernet.encrypt(b"sensitive payload"))
    ct[5] ^= 0x01  # flip a bit inside the nonce region
    with pytest.raises(EncryptionError):
        fernet.decrypt(bytes(ct))


def test_aad_must_match_to_decrypt() -> None:
    fernet = AESGCMFernet(_env())
    ct = fernet.encrypt(b"bound payload", aad=b"cookie:csrftoken")
    assert fernet.decrypt(ct, aad=b"cookie:csrftoken") == b"bound payload"
    with pytest.raises(EncryptionError):
        fernet.decrypt(ct, aad=b"cookie:other")
    with pytest.raises(EncryptionError):
        fernet.decrypt(ct)


def test_wire_version_byte_validates() -> None:
    fernet = AESGCMFernet(_env())
    ct = bytearray(fernet.encrypt(b"x"))
    ct[0] = 0x99
    with pytest.raises(EncryptionError):
        fernet.decrypt(bytes(ct))


def test_short_payload_rejected() -> None:
    fernet = AESGCMFernet(_env())
    with pytest.raises(EncryptionError):
        fernet.decrypt(b"\x01" + b"\x00" * 12)  # version + nonce, no tag


def test_empty_secret_rejected() -> None:
    with pytest.raises(ValueError, match="must be set"):
        AESGCMFernet(_env(""))


def test_legacy_default_secret_rejected() -> None:
    with pytest.raises(ValueError, match="testtoken"):
        AESGCMFernet(_env("testtoken"))


def test_short_secret_rejected() -> None:
    with pytest.raises(ValueError, match="at least 16"):
        AESGCMFernet(_env("short"))


def test_same_secret_yields_decryptable_ciphertext_across_instances() -> None:
    """Key derivation must be deterministic for a given secret so a server
    restart can still decrypt prior tokens."""
    secret = "stable-secret-of-sufficient-length-1234"
    a = AESGCMFernet(_env(secret))
    b = AESGCMFernet(_env(secret))
    ct = a.encrypt(b"persisted")
    assert b.decrypt(ct) == b"persisted"


def test_handles_empty_plaintext() -> None:
    fernet = AESGCMFernet(_env())
    ct = fernet.encrypt(b"")
    assert fernet.decrypt(ct) == b""


def test_handles_large_payload() -> None:
    fernet = AESGCMFernet(_env())
    pt = secrets.token_bytes(2 * 1024 * 1024)
    assert fernet.decrypt(fernet.encrypt(pt)) == pt
