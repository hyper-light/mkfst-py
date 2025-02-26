from base64 import b64decode
from typing import (
    Any,
    Dict,
)

import zstandard

from mkfst.logging import Logger, LogLevel
from mkfst.middleware.base import Middleware, MiddlewareType
from mkfst.middleware.base.response_context import ResponseContext
from mkfst.middleware.base.types import Handler, MiddlewareHandler, MiddlewareResult
from mkfst.models.http.parse_response import parse_response
from mkfst.models.logging import Event


class BidirectionalZStandardDecompressor(Middleware):
    def __init__(self) -> None:
        super().__init__(
            self.__class__.__name__, 
            middleware_type=MiddlewareType.BIDIRECTIONAL
        )

        self._decompressor = zstandard.ZstdDecompressor()
        self._logger = Logger()

    async def __pre__(
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
                message=f'Request - {context.method} {context.path}:{context.ip_address} - Decompressing request via ZStd'
            ))
            
            decompressed_data = b''
            try:
                headers_model = context.get_headers()
                data = context.get_bytes_arg()

                headers: Dict[str, Any] = {}
                if headers_model:
                    headers = headers_model.model_dump()

                content_encoding = headers.get(
                    "content-encoding", 
                    context.request_headers.get("x-compression-encoding")
                )

                if data != b"" and content_encoding == "zstd":
                    decompressed_data = self._decompressor.decompress(
                        data
                    )

                    context.update_request_headers({
                        key: value
                        for key, value in headers.items()
                        if key != "content-encoding" and key != "x-compression-encoding"
                    })

                    context.update_request_data(decompressed_data)

                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {context.method} {context.path}:{context.ip_address} - Decompressed request via ZStd'
                    ))
                
                else:
                    await ctx.log(Event(
                        level=LogLevel.WARN,
                        message=f'Request - {context.method} {context.path}:{context.ip_address} - No request to decompress'
                    ))

                return (
                    context,
                    response
                ), True

            except Exception as e:
                context.errors.append(e)
                context.status = 500

                await ctx.log(Event(
                    level=LogLevel.ERROR,
                    message=f'Request - {context.method} {context.path}:{context.ip_address} - Encountered error ZStd decompressing request - {str(e)}'
                ))

                return (
                    context,
                    response
                ), False

    async def __post__(
        self,
        context: ResponseContext | None = None,
        response: Any | None = None,
        handler: MiddlewareHandler | Handler | None = None,
    ) -> MiddlewareResult:
        
        async with self._logger.context(
            template="{timestamp} - {level} - {thread_id} - {message}",
        ) as ctx:
            
            try:
                content_encoding = context.response_headers.get(
                    "content-encoding", 
                    context.response_headers.get("x-compression-encoding")
                )
                
                if response is None:
                    return (
                        context,
                        response
                    ), True
                
                elif content_encoding != "zstd":
                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {context.method} {context.path}:{context.ip_address} - No content-encoding header - skipping decompression'
                    ))

                    return (
                        context,
                        response
                    ), True

                
                if isinstance(response, str):
                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {context.method} {context.path}:{context.ip_address} - Decompressing string response via ZStd'
                    ))

                    decompressed_data = self._decompressor.decompress(response.encode())

                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {context.method} {context.path}:{context.ip_address} - Decompressed response via ZStd'
                    ))

                else:
                    
                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {context.method} {context.path}:{context.ip_address} - Decompressing response via ZStd'
                    ))

                    serialized: str = parse_response(
                        response,
                        context.parser
                    )
                    decompressed_data = self._decompressor.decompress(
                        b64decode(serialized.encode())
                    )

                    context.response_headers.pop(
                        "content-encoding", 
                        context.response_headers.pop("x-compression-encoding")
                    )

                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {context.method} {context.path}:{context.ip_address} - Decompressed response via ZStd with level'
                    ))

                return (
                    context,
                    decompressed_data.decode()
                ), True

            except Exception as e:
                context.errors.append(e)
                context.status = 500

                await ctx.log(Event(
                    level=LogLevel.ERROR,
                    message=f'Request - {context.method} {context.path}:{context.ip_address} - Encountered error ZStd decompressing request - {str(e)}'
                ))

                return (
                    context,
                    response
                ), False
