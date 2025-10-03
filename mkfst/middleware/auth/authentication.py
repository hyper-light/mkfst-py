from typing import (
    Any,
    TypeVar,
    Generic,
)
from mkfst.logging import Logger, LogLevel
from mkfst.middleware.base import Middleware
from mkfst.middleware.base.response_context import ResponseContext
from mkfst.middleware.base.types import Handler, MiddlewareHandler
from mkfst.models.logging import Event


T = TypeVar("T")


class Authentication(Middleware, Generic[T]):
    def __init__(self, authenticator: T):
        self._logger = Logger()
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

        self._authenticator = authenticator

    async def __run__(
        self,
        context: ResponseContext | None = None,
        response: Any | None = None,
        handler: MiddlewareHandler | Handler | None = None,
    ):
        async with self._logger.context(
            template="{timestamp} - {level} - {thread_id} - {message}",
        ) as ctx:
            await ctx.log(
                Event(
                    level=LogLevel.DEBUG,
                    message=f"Request - {context.method} {context.path}:{context.ip_address} - Executing authentication",
                )
            )

            try:
                pass

            except Exception as e:
                context.errors.append(e)
                context.status = 500

                await ctx.log(
                    Event(
                        level=LogLevel.ERROR,
                        message=f"Request - {context.method} {context.path}:{context.ip_address} - Encountered error attempting authenticate - {str(e)}",
                    )
                )

                return (
                    context,
                    response,
                ), False
