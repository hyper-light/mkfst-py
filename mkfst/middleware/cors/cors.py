from typing import (
    Any,
    List,
    Literal,
    Optional,
    Union,
)

from mkfst.logging import Logger, LogLevel
from mkfst.middleware.base import Middleware
from mkfst.middleware.base.response_context import ResponseContext
from mkfst.middleware.base.types import Handler, MiddlewareHandler, MiddlewareResult
from mkfst.models.logging import Event

from .cors_headers import CorsHeaders


class Cors(Middleware):
    def __init__(
        self,
        access_control_allow_origin: List[str] = None,
        access_control_allow_methods: List[
            Literal["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE", "TRACE"]
        ] = None,
        access_control_expose_headers: Optional[List[str]] = None,
        access_control_max_age: Optional[Union[int, float]] = None,
        access_control_allow_credentials: Optional[bool] = None,
        access_control_allow_headers: Optional[List[str]] = None,
    ) -> None:
        self._cors_config = CorsHeaders(
            access_control_allow_origin=access_control_allow_origin,
            access_control_expose_headers=access_control_expose_headers,
            access_control_max_age=access_control_max_age,
            access_control_allow_credentials=access_control_allow_credentials,
            access_control_allow_methods=access_control_allow_methods,
            access_control_allow_headers=access_control_allow_headers,
        )

        self.origins = self._cors_config.access_control_allow_origin
        self.cors_methods = self._cors_config.access_control_allow_methods
        self.cors_headers = self._cors_config.access_control_allow_headers
        self.allow_credentials = self._cors_config.access_control_allow_credentials

        self.allow_all_origins = "*" in self._cors_config.access_control_allow_origin

        allowed_headers = self._cors_config.access_control_allow_headers
        self.allow_all_headers = False

        if allowed_headers:
            self.allow_all_headers = "*" in allowed_headers

        self.simple_headers = self._cors_config.to_simple_headers()
        self.preflight_headers = self._cors_config.to_preflight_headers()
        self.preflight_explicit_allow_origin = (
            not self.allow_all_origins or self.allow_credentials
        )

        self._logger = Logger()

        super().__init__(
            self.__class__.__name__,
            methods=["OPTIONS"],
            response_headers=self._cors_config.to_headers(),
        )

    async def __run__(
        self,
        context: ResponseContext | None = None,
        response: Any | None = None,
        handler: MiddlewareHandler | Handler | None = None,
    ) -> MiddlewareResult:
        async with self._logger.context(
            template="{timestamp} - {level} - {thread_id} - {message}",
        ) as ctx:
            
            await ctx.log(Event(
                level=LogLevel.DEBUG,
                message=f'Request - {context.method} {context.path}:{context.ip_address} - Verifying request meets CORS policy'
            ))
            
            headers = context.get_headers()
            method = context.method

            if headers:            
                parsed_headers = headers.model_dump()

            else:
                parsed_headers = {}

            origin = parsed_headers.get("origin")
            access_control_request_method: str | None = parsed_headers.get("access-control-request-method")
            access_control_request_headers: str | None = parsed_headers.get("access-control-request-headers", "")

            if method == "OPTIONS" and access_control_request_method:
                await ctx.log(Event(
                    level=LogLevel.DEBUG,
                    message=f'Request - {context.method} {context.path}:{context.ip_address} - Verifying OPTIONS request meets CORS policy'
                ))

                response_headers = dict(self.preflight_headers)

                failures: List[str] = []

                if self.allow_all_origins is False and origin not in self.origins:
                    failures.append("origin")
                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {context.method} {context.path}:{context.ip_address} - Origin of {origin} failed Allowed Origin policy'
                    ))

                elif self.preflight_explicit_allow_origin:
                    response["Access-Control-Allow-Origin"] = origin

                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {context.method} {context.path}:{context.ip_address} - Adding preflight origin of {origin}'
                    ))

                if access_control_request_method not in self.cors_methods:
                    failures.append("method")
                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {context.method} {context.path}:{context.ip_address} - Method of {method} failed Allowed Methods policy'
                    ))

                if self.allow_all_headers and access_control_request_headers is not None:
                    response_headers["Access-Control-Allow-Headers"] = (
                        access_control_request_headers
                    )
                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {context.method} {context.path}:{context.ip_address} - Adding CORS headers to response'
                    ))

                elif access_control_request_headers:
                    for header in access_control_request_headers.split(","):
                        if header.lower().strip() not in self.cors_headers:
                            failures.append("headers")
                            await ctx.log(Event(
                                level=LogLevel.DEBUG,
                                message=f'Request - {context.method} {context.path}:{context.ip_address} - Header of {header} failed Allowed Headers policy'
                            ))

                            break

                if len(failures) > 0:
                    failures_message = ", ".join(failures)
                    context.status = 401

                    context.errors.append(
                        Exception(failures_message)
                    )

                    await ctx.log(Event(
                        level=LogLevel.ERROR,
                        message=f'Request - {context.method} {context.path}:{context.ip_address} - Rejected by CORS policy with status of {context.status}'
                    ))

                    return (
                        context,
                        f"Disallowed CORS {failures_message}",
                    ), False


                context.response_headers.update(response_headers)

                context.errors.append(
                    Exception('Rejected by CORS policy')
                )

                await ctx.log(Event(
                    level=LogLevel.ERROR,
                    message=f'Request - {context.method} {context.path}:{context.ip_address} - Rejected by CORS policy with status of {context.status}'
                ))

                return (
                    context,
                    response,
                ), False

            response_headers = dict(self.simple_headers)

            if self.allow_all_origins and parsed_headers.get("cookie"):
                response_headers["access-control-allow-origin"] = origin

                await ctx.log(Event(
                    level=LogLevel.DEBUG,
                    message=f'Request - {context.method} {context.path}:{context.ip_address} - Adding allowed origin of {origin}'
                ))

            elif origin in self.origins:
                response_headers["access-control-allow-origin"] = origin

                await ctx.log(Event(
                    level=LogLevel.DEBUG,
                    message=f'Request - {context.method} {context.path}:{context.ip_address} - Adding allowed origin of {origin}'
                ))

            context.response_headers.update(response_headers)

            await ctx.log(Event(
                level=LogLevel.DEBUG,
                message=f'Request - {context.method} {context.path}:{context.ip_address} - Request met CORS policy'
            ))

            return (
                context,
                response,
            ), True
