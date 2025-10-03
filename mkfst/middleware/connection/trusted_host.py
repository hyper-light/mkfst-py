from typing import (
    Any,
)

from urllib.parse import urlunparse
from mkfst.logging import Logger, LogLevel
from mkfst.middleware.base import Middleware
from mkfst.middleware.base.response_context import ResponseContext
from mkfst.middleware.base.types import Handler, MiddlewareHandler
from mkfst.models.logging import Event

ENFORCE_DOMAIN_WILDCARD = "Domain wildcard patterns must be like '*.example.com'."


class TrustedHost(Middleware):
    def __init__(
        self,
        allowed_hosts: list[str] | None = None,
        www_redirect: bool = True,
    ):
        self._logger = Logger()
        super().__init__(
            self.__class__.__name__,
        )

        if allowed_hosts is None:
            allowed_hosts = ["*"]

        for pattern in allowed_hosts:
            assert "*" not in pattern[1:], ENFORCE_DOMAIN_WILDCARD
            if pattern.startswith("*") and pattern != "*":
                assert pattern.startswith("*."), ENFORCE_DOMAIN_WILDCARD

        self.allowed_hosts = list(allowed_hosts)
        self.allow_any = "*" in allowed_hosts
        self.www_redirect = www_redirect

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
                if self.allow_any or context.protocol not in (
                    "http",
                    "ws",
                    "https",
                    "wss",
                ):
                    context.status = 400
                    context.errors.append(Exception("Unsupported protocol"))

                    await ctx.log(
                        Event(
                            level=LogLevel.ERROR,
                            message=f"Request - {context.method} {context.path}:{context.ip_address} - Invalid protocol ",
                        )
                    )

                    return (
                        context,
                        response,
                    ), False

                host: str | None = context.request_headers.get(
                    "host",
                    context.request_headers.get("Host"),
                )

                if host is None:
                    context.status = 400
                    context.errors.append(Exception("Invalid host header"))

                    await ctx.log(
                        Event(
                            level=LogLevel.ERROR,
                            message=f"Request - {context.method} {context.path}:{context.ip_address} - Invalid host header ",
                        )
                    )

                    return (
                        context,
                        response,
                    ), False

                host, _ = host.split(":", maxsplit=1)

                is_valid_host = False
                found_www_redirect = False

                for pattern in self.allowed_hosts:
                    if host == pattern or (
                        pattern.startswith("*") and host.endswith(pattern[1:])
                    ):
                        is_valid_host = True
                        break
                    elif "www." + host == pattern:
                        found_www_redirect = True

                if is_valid_host:
                    await ctx.log(
                        Event(
                            level=LogLevel.INFO,
                            message=f"Request - {context.method} {context.path}:{context.ip_address} - {host} matched host validation scheme",
                        )
                    )

                    return (
                        context,
                        response,
                    ), True

                else:
                    if found_www_redirect and self.www_redirect:
                        url = context.to_request_url()
                        redirect_url = urlunparse(
                            url._replace(
                                netloc="www." + url.netloc,
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
                                message=f"Request - {context.method} {context.path}:{context.ip_address} - Enforcing www redirect for {host} ",
                            )
                        )

                        return (
                            context,
                            response,
                        ), False

                    context.status = 400
                    context.errors.append(Exception("Invalid host header"))

                    await ctx.log(
                        Event(
                            level=LogLevel.ERROR,
                            message=f"Request - {context.method} {context.path}:{context.ip_address} - Invalid host header ",
                        )
                    )

                    return (
                        context,
                        response,
                    ), False

            except Exception as e:
                context.errors.append(e)
                context.status = 500

                await ctx.log(
                    Event(
                        level=LogLevel.ERROR,
                        message=f"Request - {context.method} {context.path}:{context.ip_address} - Encountered error attempting trusted host check - {str(e)}",
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
