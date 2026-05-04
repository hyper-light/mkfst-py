"""CORS middleware aligned with the WHATWG Fetch spec.

Avoids the patterns audited as defective in the prior implementation:

* Origin is never reflected when the configured allowlist is wildcard AND
  credentials are enabled — that combination is rejected at construction
  time as the textbook bypass of the credentialed-CORS guard.
* Allow-Origin is rendered as a single value (per spec; the header is
  single-value), with ``Vary: Origin`` whenever the response varies on
  origin so caches don't blend responses across origins.
* Preflight rejection responses do NOT advertise any ``Access-Control-
  Allow-*`` headers — the browser sees the absence as a refusal.
* ``Access-Control-Max-Age`` is rendered as an integer, not the literal
  string ``"true"`` / ``"false"``.

Short-circuit returns use empty *string* bodies (not ``b""``) so the
response builder's existing str-only path serializes them cleanly.
"""

from __future__ import annotations

from typing import Any, List, Literal, Optional, Set, Union

from mkfst.middleware.base import Middleware
from mkfst.middleware.base.response_context import ResponseContext
from mkfst.middleware.base.types import Handler, MiddlewareHandler, MiddlewareResult

from .cors_headers import (
    SAFE_REQUEST_HEADERS,
    render_headers,
    render_max_age,
    render_methods,
)


class CorsConfigurationError(ValueError):
    """Raised when the configured CORS policy violates the Fetch spec."""


class Cors(Middleware):
    def __init__(
        self,
        access_control_allow_origin: List[str] = None,
        access_control_allow_methods: List[
            Literal["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE", "TRACE"]
        ] = None,
        access_control_expose_headers: Optional[List[str]] = None,
        access_control_max_age: Optional[Union[int, float]] = None,
        access_control_allow_credentials: bool = False,
        access_control_allow_headers: Optional[List[str]] = None,
    ) -> None:
        if not access_control_allow_origin:
            raise CorsConfigurationError(
                "access_control_allow_origin must be a non-empty list"
            )
        if not access_control_allow_methods:
            raise CorsConfigurationError(
                "access_control_allow_methods must be a non-empty list"
            )

        allow_all_origins = "*" in access_control_allow_origin
        if allow_all_origins and access_control_allow_credentials:
            raise CorsConfigurationError(
                "Cannot combine wildcard origin (*) with allow_credentials=True; "
                "browsers reject this and treating it as 'reflect' is a known "
                "auth-bypass pattern"
            )

        self._origins: Set[str] = set(access_control_allow_origin)
        self._allow_all_origins = allow_all_origins
        self._methods = list(access_control_allow_methods)
        self._allow_headers = (
            [h.lower() for h in access_control_allow_headers]
            if access_control_allow_headers
            else []
        )
        self._allow_all_headers = "*" in self._allow_headers
        self._allow_credentials = bool(access_control_allow_credentials)
        self._expose_headers = list(access_control_expose_headers or ())
        self._max_age = access_control_max_age

        # Pre-compute the static portions of the preflight response so each
        # OPTIONS request only pays for the dynamic Origin/Headers echo.
        self._preflight_static: dict[str, str] = {
            "Access-Control-Allow-Methods": render_methods(self._methods),
        }
        if self._max_age is not None:
            self._preflight_static["Access-Control-Max-Age"] = render_max_age(
                self._max_age
            )
        if self._allow_credentials:
            self._preflight_static["Access-Control-Allow-Credentials"] = "true"

        self._needs_vary = not self._allow_all_origins
        self._allowed_header_set: Set[str] = (
            SAFE_REQUEST_HEADERS | set(self._allow_headers)
        )

        super().__init__(self.__class__.__name__, methods=["OPTIONS"])

    def _origin_allowed(self, origin: str | None) -> bool:
        if origin is None:
            return False
        if self._allow_all_origins:
            return True
        return origin in self._origins

    def _resolve_acao(self, origin: str | None) -> str | None:
        if not self._origin_allowed(origin):
            return None
        if self._allow_credentials:
            return origin
        if self._allow_all_origins:
            return "*"
        return origin

    @staticmethod
    def _lookup(headers: dict[str, Any], name: str) -> str | None:
        if not headers:
            return None
        if name in headers:
            return headers[name]
        lower = name.lower()
        for k, v in headers.items():
            if k.lower() == lower:
                return v
        return None

    def _requested_headers_allowed(self, requested: str) -> bool:
        if self._allow_all_headers:
            return True
        for header in requested.split(","):
            normalized = header.strip().lower()
            if not normalized:
                continue
            if normalized not in self._allowed_header_set:
                return False
        return True

    async def __run__(
        self,
        context: ResponseContext | None = None,
        response: Any | None = None,
        handler: MiddlewareHandler | Handler | None = None,
    ) -> MiddlewareResult:
        if context is None:
            raise RuntimeError("Cors middleware requires a ResponseContext")

        request_headers = context.request_headers or {}
        origin = self._lookup(request_headers, "origin")

        if context.method == "OPTIONS" and self._lookup(
            request_headers, "access-control-request-method"
        ):
            return self._handle_preflight(context, response, origin, request_headers)

        return self._decorate_actual(context, response, origin)

    def _handle_preflight(
        self,
        context: ResponseContext,
        response: Any,
        origin: str | None,
        request_headers: dict[str, Any],
    ) -> MiddlewareResult:
        acao = self._resolve_acao(origin)
        requested_method = self._lookup(
            request_headers, "access-control-request-method"
        )
        requested_headers = (
            self._lookup(request_headers, "access-control-request-headers") or ""
        )

        ok = (
            acao is not None
            and requested_method in self._methods
            and self._requested_headers_allowed(requested_headers)
        )

        if not ok:
            # Per Fetch spec, a preflight failure is signalled by responding
            # *without* the Allow headers — browsers reject the actual
            # request from the absence. 204 = success-with-no-body.
            context.status = 204
            return (context, ""), False

        out: dict[str, str] = dict(self._preflight_static)
        out["Access-Control-Allow-Origin"] = acao

        if self._allow_all_headers:
            if requested_headers:
                out["Access-Control-Allow-Headers"] = requested_headers
        elif self._allowed_header_set:
            allowed = sorted(self._allowed_header_set)
            out["Access-Control-Allow-Headers"] = render_headers(allowed)

        if self._needs_vary:
            out["Vary"] = "Origin"

        context.response_headers.update(out)
        context.status = 204
        return (context, ""), False

    def _decorate_actual(
        self,
        context: ResponseContext,
        response: Any,
        origin: str | None,
    ) -> MiddlewareResult:
        if origin is None:
            if self._needs_vary:
                context.response_headers.setdefault("Vary", "Origin")
            return (context, response), True

        acao = self._resolve_acao(origin)
        if acao is None:
            if self._needs_vary:
                context.response_headers.setdefault("Vary", "Origin")
            return (context, response), True

        context.response_headers["Access-Control-Allow-Origin"] = acao
        if self._needs_vary or self._allow_credentials:
            context.response_headers["Vary"] = "Origin"
        if self._allow_credentials:
            context.response_headers["Access-Control-Allow-Credentials"] = "true"
        if self._expose_headers:
            context.response_headers["Access-Control-Expose-Headers"] = render_headers(
                self._expose_headers
            )
        return (context, response), True
