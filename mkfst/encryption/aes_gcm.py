"""Authenticated encryption built on AES-GCM-256.

Construction:

    [version(1)] || [nonce(12)] || [ciphertext || tag(16)]

A 32-byte content-encryption key is derived once from the configured
``MERCURY_SYNC_AUTH_SECRET`` via HKDF-SHA256 and reused for every message.
Per-message ``nonce`` is 96 bits of CSPRNG output. Initialization is the
expensive operation (HKDF + AESGCM construction); per-call ``encrypt``/
``decrypt`` reuse the cached ``AESGCM`` instance and pay only the
``secrets.token_bytes(12)`` + OpenSSL AEAD round trip.

Pre-fix the implementation generated a random key per message and
prepended it to the ciphertext; ``decrypt`` then read the key out of the
ciphertext. That provided no confidentiality whatsoever — anyone holding
the bytes could decrypt them.
"""

from __future__ import annotations

import secrets
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from mkfst.env import Env

_VERSION: Final[int] = 0x01
_NONCE_SIZE: Final[int] = 12
_TAG_SIZE: Final[int] = 16
_KEY_SIZE: Final[int] = 32
_HEADER_SIZE: Final[int] = 1 + _NONCE_SIZE
_MIN_PAYLOAD: Final[int] = _HEADER_SIZE + _TAG_SIZE
_HKDF_INFO: Final[bytes] = b"mkfst.aes-gcm-256.v1"
_LEGACY_DEFAULT: Final[str] = "testtoken"
_MIN_SECRET_BYTES: Final[int] = 16


class EncryptionError(Exception):
    """Raised when ciphertext authentication fails or input is malformed."""


class AESGCMFernet:
    __slots__ = ("_aead",)

    def __init__(self, env: Env) -> None:
        self._aead = AESGCM(self._derive_key(env.MERCURY_SYNC_AUTH_SECRET))

    @staticmethod
    def _derive_key(secret: str | bytes) -> bytes:
        if isinstance(secret, str):
            secret_bytes = secret.encode("utf-8")
        else:
            secret_bytes = bytes(secret)

        if not secret_bytes:
            raise ValueError(
                "MERCURY_SYNC_AUTH_SECRET must be set to a non-empty value when "
                "encryption-dependent middleware (CSRF, wire encryption) is used."
            )
        if secret_bytes == _LEGACY_DEFAULT.encode():
            raise ValueError(
                "MERCURY_SYNC_AUTH_SECRET still uses the deprecated default "
                f"value {_LEGACY_DEFAULT!r}. Generate a high-entropy secret of "
                f"at least {_MIN_SECRET_BYTES} bytes (e.g. "
                "`python -c 'import secrets; print(secrets.token_urlsafe(32))'`)."
            )
        if len(secret_bytes) < _MIN_SECRET_BYTES:
            raise ValueError(
                f"MERCURY_SYNC_AUTH_SECRET must be at least {_MIN_SECRET_BYTES} "
                f"bytes; got {len(secret_bytes)}."
            )

        return HKDF(
            algorithm=hashes.SHA256(),
            length=_KEY_SIZE,
            salt=None,
            info=_HKDF_INFO,
        ).derive(secret_bytes)

    def encrypt(self, data: bytes, aad: bytes = b"") -> bytes:
        nonce = secrets.token_bytes(_NONCE_SIZE)
        ciphertext = self._aead.encrypt(nonce, data, aad)
        # Single allocation: bytes() of bytearray with all three regions
        # written contiguously. Avoids the intermediate concatenation list
        # the obvious ``bytes([_VERSION]) + nonce + ciphertext`` would build.
        out = bytearray(_HEADER_SIZE + len(ciphertext))
        out[0] = _VERSION
        out[1:_HEADER_SIZE] = nonce
        out[_HEADER_SIZE:] = ciphertext
        return bytes(out)

    def decrypt(self, data: bytes, aad: bytes = b"") -> bytes:
        if len(data) < _MIN_PAYLOAD:
            raise EncryptionError("ciphertext shorter than minimum framed length")

        view = memoryview(data)
        if view[0] != _VERSION:
            raise EncryptionError(f"unsupported wire version: 0x{view[0]:02x}")

        nonce = bytes(view[1:_HEADER_SIZE])
        ciphertext = bytes(view[_HEADER_SIZE:])
        try:
            return self._aead.decrypt(nonce, ciphertext, aad)
        except InvalidTag as exc:
            raise EncryptionError("authentication tag verification failed") from exc
