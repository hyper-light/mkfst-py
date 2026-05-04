"""Double-submit CSRF middleware.

The token is a fixed-size, AES-GCM-authenticated payload of the form

    [random(N)] || [issued_at_ms_be(8)]

encrypted with the CEK derived from ``MERCURY_SYNC_AUTH_SECRET`` and bound to
the cookie name via the AEAD's associated-data field. Validation requires the
ciphertext attached to the request header (``x-csrftoken`` by default) to
decrypt under the same key+AAD AND to ``compare_digest``-match the cookie's
plaintext after decryption. Tokens older than ``max_age`` are rejected.

The cookie itself is intentionally JS-readable (``HttpOnly=False``) because the
double-submit pattern requires the client to copy the cookie value into a
request header. Combine with ``Secure`` (default ``True``) and ``SameSite=lax``
(default) to neutralize CSRF without giving up XHR semantics.
"""

from __future__ import annotations

import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from http.cookies import BaseCookie, SimpleCookie
from secrets import compare_digest, token_bytes
from typing import Any, Literal

from mkfst.encryption import AESGCMFernet, EncryptionError
from mkfst.env import Env, load_env
from mkfst.logging import Logger
from mkfst.middleware.base import Middleware
from mkfst.middleware.base.response_context import ResponseContext
from mkfst.middleware.base.types import Handler, MiddlewareHandler, MiddlewareResult

_TIMESTAMP_BYTES = 8
_DEFAULT_NONCE_BYTES = 16


class CSRFConfigurationError(ValueError):
    """Raised when the middleware is asked to do something that defeats its purpose."""


class CSRFRejection(Exception):
    """Raised internally when a token fails to validate."""


def _b64encode(data: bytes) -> str:
    return urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = (-len(data)) % 4
    return urlsafe_b64decode(data + "=" * padding)


class CSRF(Middleware):
    def __init__(
        self,
        nonce_bytes: int = _DEFAULT_NONCE_BYTES,
        required_paths: list[str] | None = None,
        exempt_paths: list[str] | None = None,
        sensitive_cookies: set[str] | None = None,
        safe_methods: list[
            Literal["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE", "TRACE"]
        ] = ("GET", "HEAD", "OPTIONS", "TRACE"),
        cookie_name: str = "csrftoken",
        cookie_path: str = "/",
        cookie_domain: str | None = None,
        cookie_secure: bool = True,
        cookie_httponly: bool = False,
        cookie_samesite: Literal["lax", "strict", "none"] = "lax",
        header_name: str = "x-csrftoken",
        max_age_seconds: int = 60 * 60,
    ) -> None:
        if nonce_bytes < 8:
            raise CSRFConfigurationError(
                f"nonce_bytes must be at least 8 (got {nonce_bytes}); "
                "anything smaller leaks structure to attackers and breaks "
                "compare_digest's length-equality preconditions"
            )
        if cookie_samesite == "none" and not cookie_secure:
            raise CSRFConfigurationError("cookie_samesite='none' requires cookie_secure=True")

        env = load_env(Env)
        self._encryptor = AESGCMFernet(env)
        self._nonce_bytes = nonce_bytes
        self._aad = cookie_name.encode("ascii")
        self._max_age_ms = int(max_age_seconds * 1000)

        self.required_paths = list(required_paths) if required_paths else []
        self.exempt_paths = list(exempt_paths) if exempt_paths else []
        self.sensitive_cookies = set(sensitive_cookies) if sensitive_cookies else set()
        self.safe_methods = set(safe_methods)
        self.cookie_name = cookie_name
        self.cookie_path = cookie_path
        self.cookie_domain = cookie_domain
        self.cookie_secure = cookie_secure
        self.cookie_httponly = cookie_httponly
        self.cookie_samesite = cookie_samesite
        self.header_name = header_name

        self._logger = Logger()

        super().__init__(self.__class__.__name__, response_headers={})

    def _issue_token(self) -> str:
        random_part = token_bytes(self._nonce_bytes)
        timestamp_part = int(time.time() * 1000).to_bytes(_TIMESTAMP_BYTES, "big")
        ciphertext = self._encryptor.encrypt(random_part + timestamp_part, aad=self._aad)
        return _b64encode(ciphertext)

    def _decode_token(self, token: str) -> bytes:
        """Return the random + timestamp plaintext, raising on tamper or expiry."""
        try:
            framed = _b64decode(token)
        except (ValueError, TypeError) as exc:
            raise CSRFRejection("malformed token encoding") from exc

        try:
            plaintext = self._encryptor.decrypt(framed, aad=self._aad)
        except EncryptionError as exc:
            raise CSRFRejection("token authentication failed") from exc

        if len(plaintext) != self._nonce_bytes + _TIMESTAMP_BYTES:
            raise CSRFRejection("token plaintext length mismatch")

        if self._max_age_ms > 0:
            issued_at = int.from_bytes(plaintext[-_TIMESTAMP_BYTES:], "big")
            now_ms = int(time.time() * 1000)
            if now_ms - issued_at > self._max_age_ms:
                raise CSRFRejection("token expired")
            if issued_at - now_ms > 60_000:
                # Clock skew tolerance of a minute in the future. Anything
                # further is a forgery / clock-corruption signal.
                raise CSRFRejection("token issued in the future")

        return plaintext[: self._nonce_bytes]

    def _has_sensitive_cookies(self, cookies: dict[str, str]) -> bool:
        return any(name in cookies for name in self.sensitive_cookies)

    def _path_in(self, path: str, paths: list[str]) -> bool:
        return any(p in path for p in paths)

    def _build_set_cookie(self, token: str) -> str:
        cookie: BaseCookie = SimpleCookie()
        cookie[self.cookie_name] = token
        morsel = cookie[self.cookie_name]
        morsel["path"] = self.cookie_path
        if self.cookie_secure:
            morsel["secure"] = True
        if self.cookie_httponly:
            morsel["httponly"] = True
        morsel["samesite"] = self.cookie_samesite.capitalize()
        if self.cookie_domain is not None:
            morsel["domain"] = self.cookie_domain
        if self._max_age_ms > 0:
            morsel["max-age"] = str(self._max_age_ms // 1000)
        return cookie.output(header="").strip()

    @staticmethod
    def _parse_cookie_header(value: str | None) -> dict[str, str]:
        """Parse a raw ``Cookie:`` header into a name→value mapping. Avoids
        SimpleCookie because it accepts and silently coerces malformed cookies;
        we want a strict, allocation-light parser on the hot path."""
        if not value:
            return {}
        out: dict[str, str] = {}
        for pair in value.split(";"):
            pair = pair.strip()
            if not pair or "=" not in pair:
                continue
            k, _, v = pair.partition("=")
            out[k.strip()] = v.strip().strip('"')
        return out

    @staticmethod
    def _lookup_header(headers: dict[str, Any], name: str) -> str | None:
        """Case-insensitive single-pass lookup. Most parsers normalize to
        lowercase but we belt-and-brace here."""
        if not headers:
            return None
        if name in headers:
            return headers[name]
        lower = name.lower()
        for k, v in headers.items():
            if k.lower() == lower:
                return v
        return None

    async def __run__(
        self,
        context: ResponseContext | None = None,
        response: Any | None = None,
        handler: MiddlewareHandler | Handler | None = None,
    ) -> MiddlewareResult:
        if context is None:
            raise RuntimeError("CSRF middleware requires a ResponseContext")

        async with self._logger.context(
            template="{timestamp} - {level} - {thread_id} - {message}",
        ) as ctx:
            request_headers = context.request_headers or {}
            cookie_header = self._lookup_header(request_headers, "cookie")
            cookies = self._parse_cookie_header(cookie_header)

            request_path = context.path
            request_method = context.method
            cookie_token = cookies.get(self.cookie_name)

            unsafe_method = request_method not in self.safe_methods
            path_required = (
                self._path_in(request_path, self.required_paths) if self.required_paths else False
            )
            path_exempt = (
                self._path_in(request_path, self.exempt_paths) if self.exempt_paths else False
            )
            sensitive = bool(self.sensitive_cookies) and self._has_sensitive_cookies(cookies)

            # Only unsafe methods are subject to CSRF; the protection is
            # against state-changing requests forged via cross-site contexts.
            # Safe methods (GET/HEAD/OPTIONS/TRACE) are by definition idempotent
            # and read-only, so they need no token check.
            must_validate = unsafe_method and not path_exempt and (path_required or sensitive)

            if must_validate:
                submitted = self._lookup_header(request_headers, self.header_name)

                if cookie_token is None or submitted is None:
                    return self._reject(context, response, "missing csrf material", ctx)

                try:
                    cookie_plain = self._decode_token(cookie_token)
                    submitted_plain = self._decode_token(submitted)
                except CSRFRejection as e:
                    return self._reject(context, response, str(e), ctx)

                if not compare_digest(cookie_plain, submitted_plain):
                    return self._reject(context, response, "csrf token mismatch", ctx)

            if cookie_token is None:
                token = self._issue_token()
                context.response_headers["set-cookie"] = self._build_set_cookie(token)
                context.response_headers[self.header_name] = token

            return (context, response), True

    def _reject(
        self,
        context: ResponseContext,
        response: Any,
        reason: str,
        ctx,
    ) -> MiddlewareResult:
        context.status = 403
        return (
            context,
            f"CSRF token verification failed: {reason}",
        ), False
