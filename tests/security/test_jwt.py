from __future__ import annotations

import time

import pytest

from mkfst.auth.jose import jwt
from mkfst.auth.jose.exceptions import (
    ExpiredSignatureError,
    JWTClaimsError,
    JWTError,
)

SECRET = "test-secret-bytes-32-chars-long!!"


def _claims(**extra) -> dict:
    base = {"exp": int(time.time()) + 3600, "iat": int(time.time())}
    base.update(extra)
    return base


def test_roundtrip_hs256() -> None:
    token = jwt.encode(_claims(sub="alice"), SECRET, algorithm="HS256")
    decoded = jwt.decode(token, SECRET, algorithms=["HS256"])
    assert decoded["sub"] == "alice"


def test_decode_requires_explicit_algorithms() -> None:
    """Pre-fix, decode(token, key) accepted any alg; the call signature now
    forces the caller to pass an explicit allowlist."""
    token = jwt.encode(_claims(), SECRET, algorithm="HS256")
    with pytest.raises(TypeError):
        jwt.decode(token, SECRET)  # type: ignore[call-arg]


def test_decode_rejects_none_in_allowlist() -> None:
    token = jwt.encode(_claims(), SECRET, algorithm="HS256")
    with pytest.raises(JWTError, match="alg=none"):
        jwt.decode(token, SECRET, algorithms=["none"])


def test_decode_rejects_alg_none_token() -> None:
    """Even if the allowlist includes only HS256, an attacker-supplied token
    with alg=none in its header must not be silently accepted."""
    # Manually construct an alg=none token.
    import base64

    def _b64(d: bytes) -> bytes:
        return base64.urlsafe_b64encode(d).rstrip(b"=")

    header = _b64(b'{"alg":"none","typ":"JWT"}')
    payload = _b64(b'{"sub":"attacker"}')
    token = (header + b"." + payload + b".").decode()
    with pytest.raises(JWTError):
        jwt.decode(token, SECRET, algorithms=["HS256"])


def test_decode_requires_exp_by_default() -> None:
    token = jwt.encode({"sub": "alice", "iat": int(time.time())}, SECRET, algorithm="HS256")
    with pytest.raises(JWTError, match='missing required key "exp"'):
        jwt.decode(token, SECRET, algorithms=["HS256"])


def test_decode_can_opt_out_of_exp_requirement() -> None:
    token = jwt.encode({"sub": "alice", "iat": int(time.time())}, SECRET, algorithm="HS256")
    decoded = jwt.decode(
        token,
        SECRET,
        algorithms=["HS256"],
        options={"require_exp": False},
    )
    assert decoded["sub"] == "alice"


def test_decode_rejects_expired_token() -> None:
    token = jwt.encode(
        {"sub": "alice", "iat": int(time.time()) - 7200, "exp": int(time.time()) - 60},
        SECRET,
        algorithm="HS256",
    )
    with pytest.raises(ExpiredSignatureError):
        jwt.decode(token, SECRET, algorithms=["HS256"])


def test_decode_rejects_wrong_alg_in_token() -> None:
    """If the token says HS512 but allowlist is HS256, reject."""
    token = jwt.encode(_claims(), SECRET, algorithm="HS512")
    with pytest.raises(JWTError, match="not allowed"):
        jwt.decode(token, SECRET, algorithms=["HS256"])


def test_decode_rejects_mixed_hmac_asymmetric_allowlist() -> None:
    token = jwt.encode(_claims(), SECRET, algorithm="HS256")
    with pytest.raises(JWTError, match="alg-confusion"):
        jwt.decode(token, SECRET, algorithms=["HS256", "RS256"])


def test_decode_rejects_empty_algorithms() -> None:
    token = jwt.encode(_claims(), SECRET, algorithm="HS256")
    with pytest.raises(JWTError, match="non-empty"):
        jwt.decode(token, SECRET, algorithms=[])


def test_decode_rejects_tampered_signature() -> None:
    token = jwt.encode(_claims(), SECRET, algorithm="HS256")
    parts = token.split(".")
    parts[2] = parts[2][::-1]  # Reverse the signature.
    tampered = ".".join(parts)
    with pytest.raises(JWTError):
        jwt.decode(tampered, SECRET, algorithms=["HS256"])


def test_decode_validates_audience_when_present() -> None:
    token = jwt.encode(_claims(aud="api.example"), SECRET, algorithm="HS256")
    decoded = jwt.decode(token, SECRET, algorithms=["HS256"], audience="api.example")
    assert decoded["aud"] == "api.example"

    with pytest.raises(JWTClaimsError):
        jwt.decode(token, SECRET, algorithms=["HS256"], audience="other.example")


def test_decode_validates_issuer_when_present() -> None:
    token = jwt.encode(_claims(iss="https://issuer.example"), SECRET, algorithm="HS256")
    decoded = jwt.decode(token, SECRET, algorithms=["HS256"], issuer="https://issuer.example")
    assert decoded["iss"] == "https://issuer.example"

    with pytest.raises(JWTClaimsError):
        jwt.decode(token, SECRET, algorithms=["HS256"], issuer="https://other.example")


def test_decode_rejects_nbf_in_future() -> None:
    token = jwt.encode(_claims(nbf=int(time.time()) + 3600), SECRET, algorithm="HS256")
    with pytest.raises(JWTClaimsError, match="not yet valid"):
        jwt.decode(token, SECRET, algorithms=["HS256"])
