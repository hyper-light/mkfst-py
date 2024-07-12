from base64 import b64encode
from gzip import compress
from typing import (
    Any,
    Callable,
    Dict,
    Union,
)

from mkfst.logging import Logger, LogLevel
from mkfst.middleware.base import Middleware, MiddlewareType
from mkfst.middleware.base.response_context import ResponseContext
from mkfst.middleware.base.types import Handler, MiddlewareHandler, MiddlewareResult
from mkfst.models.http.parse_response import parse_response
from mkfst.models.logging import Event


class BidirectionalGZipCompressor(Middleware):
    def __init__(
        self,
        compression_level: int = 9,
        serializers: Dict[
            str, Callable[..., Union[str, None]]
        ] = {},
    ) -> None:
        super().__init__(
            self.__class__.__name__, 
            middleware_type=MiddlewareType.BIDIRECTIONAL,
            response_headers={
                "x-compression-encoding": "gzip"
            }
        )

        self.compression_level = compression_level
        self.serializers = serializers
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
                message=f'Request - {context.method} {context.path}:{context.ip_address} - Compressing request via GZip with level {self.compression_level} compression'
            ))
            
            data = context.get_bytes_arg()
            compressed_data = b''
            try:
                if data != b"":
                    compressed_data = compress(
                        data, 
                        compresslevel=self.compression_level,
                    )

                    context.update_request_data(compressed_data)
                    context.update_request_headers({
                        "x-compression-encoding": "gzip"
                    })

                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {context.method} {context.path}:{context.ip_address} - Compressed request via GZip with level {self.compression_level} compression'
                    ))

                else:
                    await ctx.log(Event(
                        level=LogLevel.WARN,
                        message=f'Request - {context.method} {context.path}:{context.ip_address} - No request to compress'
                    ))

                return (
                    context,
                    response
                ), True

            except Exception as e:
                context.compressor = 'gzip'
                context.compression_level = self.compression_level
                context.errors.append(e)
                context.status = 500

                await ctx.log(Event(
                    level=LogLevel.ERROR,
                    message=f'Request - {context.method} {context.path}:{context.ip_address} - Encountered error GZip compressing request - {str(e)}'
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
    ):
        async with self._logger.context(
            template="{timestamp} - {level} - {thread_id} - {message}",
        ) as ctx:
            try:
                if response is None:
                    await ctx.log(Event(
                        level=LogLevel.WARN,
                        message=f'Request - {context.method} {context.path}:{context.ip_address} - No response to compress'
                    ))

                    return (
                        context,
                        response
                    ), True

                elif isinstance(response, str):
                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {context.method} {context.path}:{context.ip_address} - Compressing string response via GZip with level {self.compression_level} compression'
                    ))
                    
                    compressed_data = compress(
                        response.encode(), 
                        compresslevel=self.compression_level,
                    )

                    context.response_headers["x-compression-encoding"] = "gzip"

                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {context.method} {context.path}:{context.ip_address} - Compressed response via GZip with level {self.compression_level} compression'
                    ))
                    
                    return (
                        context,
                        b64encode(compressed_data).decode()
                    ), True

                else:
                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {context.method} {context.path}:{context.ip_address} - Compressing response via GZip with level {self.compression_level} compression'
                    ))

                    serialized = parse_response(
                        response,
                        context.parser
                    )

                    compressed_data = compress(
                        serialized, compresslevel=self.compression_level
                    )

                    context.response_headers["x-compression-encoding"] = "gzip"

                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {context.method} {context.path}:{context.ip_address} - Compressed response via GZip with level {self.compression_level} compression'
                    ))

                    return (
                        context,
                        b64encode(compressed_data).decode()
                    ), True

            except Exception as e:
                context.compressor = 'gzip'
                context.compression_level = self.compression_level
                context.errors.append(e)
                context.status = 500

                await ctx.log(Event(
                    level=LogLevel.ERROR,
                    message=f'Request - {context.method} {context.path}:{context.ip_address} - Encountered error GZip compressing request - {str(e)}'
                ))

                return (
                    context,
                    response,
                ), False

    async def close(self):
        await self._logger.close()

    def abort(self):
        self._logger.abort()