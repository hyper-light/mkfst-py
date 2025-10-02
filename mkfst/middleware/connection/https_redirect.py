import re
from typing import (
    Any,
    Literal,
)
from urllib.parse import urlunparse
from mkfst.logging import Logger, LogLevel
from mkfst.middleware.base import Middleware
from mkfst.middleware.base.response_context import ResponseContext
from mkfst.middleware.base.types import Handler, MiddlewareHandler
from mkfst.models.logging import Event


class HTTPSRedirect(Middleware):
    def __init__(self):
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

        self._scheme: dict[Literal["http", "ws"], Literal["https", "wss"]] = {
            "http": "https",
            "ws": "wss",
        }

        self._port_pattern = re.compile(":\d{4}")

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
                    message=f"Request - {context.method} {context.path}:{context.ip_address} - Checking for HTTPS redirect",
                )
            )

            try:
                if (
                    context.protocol in ["http", "ws"]
                    and context.upgrade_port is not None
                ):
                    redirect_scheme = self._scheme[context.protocol]

                    url = context.to_request_url()

                    redirect_url = urlunparse(
                        url._replace(
                            scheme=redirect_scheme,
                            netloc=self._port_pattern.sub(
                                f":{context.upgrade_port}",
                                url.netloc,
                                count=1,
                            ),
                        )
                    )

                    context.status = 307
                    context.response_headers.update(
                        {
                            "location": redirect_url,
                        }
                    )

                    await ctx.log(
                        Event(
                            level=LogLevel.INFO,
                            message=f"Request - {context.method} {context.path}:{context.ip_address} - Enforcing {redirect_url} redirect",
                        )
                    )

                    return (
                        context,
                        response,
                    ), False

                else:
                    return (
                        context,
                        response,
                    ), True

            except Exception as e:
                context.errors.append(e)
                context.status = 500

                await ctx.log(
                    Event(
                        level=LogLevel.ERROR,
                        message=f"Request - {context.method} {context.path}:{context.ip_address} - Encountered error attempting HTTPS redirect - {str(e)}",
                    )
                )

                return (
                    context,
                    response,
                ), False

    async def close(self):
        pass

    def abort(self):
        pass
