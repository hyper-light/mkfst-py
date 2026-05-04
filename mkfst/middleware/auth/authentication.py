"""Pluggable authentication middleware.

Accepts any callable (sync or async) that takes a ``ResponseContext`` and
returns one of:

* ``True``                          → authenticated, no principal attached
* ``False`` / ``None``              → rejected (default 401 Unauthorized)
* ``(True, principal)``             → authenticated, ``principal`` attached to ``context.principal``
* ``(False, reason: str)``          → rejected with ``reason`` returned as the response body
* a non-bool, non-tuple object      → treated as a principal (authenticated)

The authenticator's call form is inspected once at construction time so
the per-request hot path doesn't pay an ``inspect`` call.
"""

from __future__ import annotations

import inspect
from typing import Any, Generic, Optional, TypeVar

from mkfst.logging import Logger, LogLevel
from mkfst.middleware.base import Middleware
from mkfst.middleware.base.response_context import ResponseContext
from mkfst.middleware.base.types import Handler, MiddlewareHandler, MiddlewareResult
from mkfst.models.logging import Event

T = TypeVar("T")


class Authentication(Middleware, Generic[T]):
    def __init__(
        self,
        authenticator: T,
        *,
        failure_status: int = 401,
        failure_message: str = "Unauthorized",
        www_authenticate: Optional[str] = None,
    ) -> None:
        if not callable(authenticator):
            raise TypeError(
                "Authentication middleware requires a callable authenticator; "
                f"got {type(authenticator).__name__}"
            )

        self._logger = Logger()
        self._authenticator = authenticator
        self._failure_status = failure_status
        self._failure_message = failure_message
        self._www_authenticate = www_authenticate
        self._is_async = self._detect_async(authenticator)

        super().__init__(
            self.__class__.__name__,
            methods=[
                "DELETE",
                "GET",
                "HEAD",
                "OPTIONS",
                "PATCH",
                "POST",
                "PUT",
                "TRACE",
            ],
        )

    @staticmethod
    def _detect_async(call: Any) -> bool:
        if inspect.iscoroutinefunction(call):
            return True
        underlying = getattr(call, "__call__", None)
        if underlying is not None and inspect.iscoroutinefunction(underlying):
            return True
        return False

    @staticmethod
    def _normalize(result: Any) -> tuple[bool, Any]:
        if result is True:
            return True, None
        if result is False or result is None:
            return False, None
        if isinstance(result, tuple) and len(result) == 2:
            ok, payload = result
            return bool(ok), payload
        return True, result

    async def _invoke(self, context: ResponseContext) -> Any:
        if self._is_async:
            return await self._authenticator(context)
        return self._authenticator(context)

    async def __run__(
        self,
        context: ResponseContext | None = None,
        response: Any | None = None,
        handler: MiddlewareHandler | Handler | None = None,
    ) -> MiddlewareResult:
        if context is None:
            raise RuntimeError("Authentication middleware requires a ResponseContext")

        async with self._logger.context(
            template="{timestamp} - {level} - {thread_id} - {message}",
        ) as ctx:
            try:
                ok, payload = self._normalize(await self._invoke(context))
            except Exception as e:
                context.errors.append(e)
                context.status = 500
                await ctx.log(
                    Event(
                        level=LogLevel.ERROR,
                        message=(
                            f"Request - {context.method} {context.path}:"
                            f"{context.ip_address} - Authenticator raised "
                            f"{type(e).__name__}: {e}"
                        ),
                    )
                )
                return (context, response), False

            if not ok:
                context.status = self._failure_status
                if self._www_authenticate is not None:
                    context.response_headers["www-authenticate"] = self._www_authenticate
                body = (
                    payload
                    if isinstance(payload, str) and payload
                    else self._failure_message
                )
                await ctx.log(
                    Event(
                        level=LogLevel.INFO,
                        message=(
                            f"Request - {context.method} {context.path}:"
                            f"{context.ip_address} - Authentication rejected"
                        ),
                    )
                )
                return (context, body), False

            if payload is not None:
                context.principal = payload

            return (context, response), True
