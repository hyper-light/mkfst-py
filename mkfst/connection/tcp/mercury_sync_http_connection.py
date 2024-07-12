from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections import defaultdict, deque
from typing import Any, Callable, Deque, Dict, List, Literal, Optional, Tuple, Union

import orjson
import psutil
from pydantic import BaseModel

from mkfst.connection.base.connection_type import ConnectionType
from mkfst.env import Env
from mkfst.logging import Logger, LogLevel
from mkfst.middleware.base.response_context import ResponseContext
from mkfst.models.http import (
    HTTPResponse,
    parse_response,
)
from mkfst.models.logging import Event, Response
from mkfst.rate_limiting import Limiter

from .fabricator import Fabricator
from .mercury_sync_tcp_connection import MercurySyncTCPConnection
from .router import Router

Handler = Callable[..., Tuple[Any, int]]


class MercurySyncHTTPConnection(MercurySyncTCPConnection):
    def __init__(
        self,
        host: str,
        port: int,
        instance_id: int,
        env: Env,
    ) -> None:
        super().__init__(host, port, instance_id, env)

        self.env = env
        self._waiters: Deque[asyncio.Future] = deque()
        self._connections: Dict[str, List[asyncio.Transport]] = defaultdict(list)
        self._http_socket: Union[socket.socket, None] = None
        self._hostnames: Dict[Tuple[str, int], str] = {}
        self._max_concurrency = env.MERCURY_SYNC_MAX_CONCURRENCY

        self.connection_type = ConnectionType.HTTP
        self._is_server = env.MERCURY_SYNC_USE_HTTP_SERVER
        self._use_encryption = env.MERCURY_SYNC_USE_HTTP_MSYNC_ENCRYPTION

        self._supported_handlers: Dict[str, Dict[str, str]] = defaultdict(dict)
        self._response_parsers: Dict[BaseModel, Tuple[Callable[[Any], str], int]] = {}
        self._response_headers: Dict[str, Dict[str, Any]] = {}

        self._middleware_enabled: Dict[str, bool] = {}

        self._limiter = Limiter(env)

        self._backoff_sem: Union[asyncio.Semaphore, None] = None

        rate_limit_strategy = env.MERCURY_SYNC_HTTP_RATE_LIMIT_STRATEGY
        self._rate_limiting_enabled = rate_limit_strategy != "none"
        self._rate_limiting_backoff_rate = env.MERCURY_SYNC_HTTP_RATE_LIMIT_BACKOFF_RATE

        self._initial_cpu = psutil.cpu_percent()
        self._path_param_pattern = re.compile(r"(:\w+)")
        self.routes = Router()
        self.match_routes = {}

        self.fabricators: Dict[str, Fabricator] = {}
        self._logger = Logger()

    def from_env(self, env: Env):

        super().from_env(env)

        self._max_concurrency = env.MERCURY_SYNC_MAX_CONCURRENCY
        self._is_server = env.MERCURY_SYNC_USE_HTTP_SERVER
        self._use_encryption = env.MERCURY_SYNC_USE_HTTP_MSYNC_ENCRYPTION
        rate_limit_strategy = env.MERCURY_SYNC_HTTP_RATE_LIMIT_STRATEGY
        self._rate_limiting_enabled = rate_limit_strategy != "none"
        self._rate_limiting_backoff_rate = env.MERCURY_SYNC_HTTP_RATE_LIMIT_BACKOFF_RATE

    async def connect_async(
        self,
        cert_path: Optional[str] = None,
        key_path: Optional[str] = None,
        worker_socket: Optional[socket.socket] = None
    ):
        async with self._logger.context() as ctx:

            self._backoff_sem = asyncio.Semaphore(self._rate_limiting_backoff_rate)

            await ctx.log(Event(
                level=LogLevel.DEBUG,
                message=f'Starting HTTP connection on - {self.host}:{self.port}'
            ))
            
            return await super().connect_async(
                cert_path=cert_path,
                key_path=key_path,
                worker_socket=worker_socket,
            )


    def read(self, data: bytes, transport: asyncio.Transport) -> None:
        self._pending_responses.append(
            asyncio.create_task(self._route_request(data, transport))
        )

    async def _route_request(self, data: bytes, transport: asyncio.Transport):

        async with self._logger.context() as ctx:

            method: str | None = None
            path: str | None = None
            request_type: str | None = None
            request_data: List[bytes] | None = []
            query: str | None = None
            
            ip_address, _ = transport.get_extra_info('peername')

            try:
                if self._use_encryption:
                    encrypted_data = self._encryptor.encrypt(data)
                    data = self._compressor.compress(encrypted_data)

                request_data = data.split(b"\r\n")
                method, path, request_type = request_data[0].decode().split(" ")


                await ctx.log(Event(
                    level=LogLevel.DEBUG,
                    message=f'Request - {method} {path}:{ip_address} - received'
                ))

                query: Union[str, None] = None
                if "?" in path:
                    path, query = path.split("?")

                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {method} {path}:{ip_address} - received query - {query}'
                    ))

            except Exception as e:
                async with self._backoff_sem:

                    await ctx.log(
                        Response(
                            level=LogLevel.ERROR,
                            ip_address=ip_address,
                            error=str(e),
                            status=400
                        ),
                        template="{timestamp} - {level} - {thread_id} - {ip_address}:{status}:{error}"
                    )

                    if transport.is_closing() is False:
                        server_error_respnse = HTTPResponse(
                            status=400,
                            error=f"Internal Error - {str(e)}",
                            protocol='HTTP/1.1',
                        )

                        transport.write(server_error_respnse.prepare_response())

                return
            
            handler_key = f"{method}_{path}"

            handler: Handler | None = None
            fabricator: Fabricator | None = None
            params: Dict[str, str | Tuple[str]] | None = None

            try:
                handler = self.events[handler_key]
                fabricator = self.fabricators[handler_key]

                await ctx.log(Event(
                    level=LogLevel.DEBUG,
                    message=f'Request - {method} {path}:{ip_address} - successful exact match for route'
                ))

            except KeyError:
                # Fallback to Trie router
                if match := self.routes.match(path):
                    methods_conifg: Dict[
                        str, Dict[Literal["model", "handler"], Handler | Any]
                    ] = match.anything

                    resolved_route = match.route
                    handler = methods_conifg.get(method)
                    handler_key = f"{method}_{resolved_route}"
                    params = match.params
                    fabricator = self.fabricators[handler_key]

                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {method} {path}:{ip_address} - successful partial match for route'
                    ))


            try:
                if handler is None:
                    raise KeyError("Route not found.")

                if self._rate_limiting_enabled:
                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {method} {path}:{ip_address} - entered rate limiting'
                    ))

                    rejected = await self._limiter.limit(
                        ipaddress.ip_address(ip_address),
                        path,
                        method,
                        limit=handler.limit,
                    )

                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {method} {path}:{ip_address} - rate limiting returned status - {rejected}'
                    ))

                    if rejected and transport.is_closing() is False:
                        async with self._backoff_sem:

                            await ctx.log(
                                Response(
                                    path=path,
                                    method=method,
                                    level=LogLevel.ERROR,
                                    ip_address=ip_address,
                                    error='Rejected by rate limiting',
                                    status=429
                                ),
                                template="{timestamp} - {level} - {thread_id} - {ip_address}:{status} - {method} {path} {error}"
                            )

                            too_many_requests_response = HTTPResponse(
                                path=path,
                                status=429,
                                error="Too Many Requests",
                                protocol=request_type,
                                method=method,
                            )

                            transport.write(too_many_requests_response.prepare_response())

                            return

                    elif rejected:
                        await ctx.log(
                            Response(
                                path=path,
                                method=method,
                                level=LogLevel.ERROR,
                                ip_address=ip_address,
                                error='Rejected by rate limiting and transport closed - aborting request',
                                status=429
                            ),
                            template="{timestamp} - {level} - {thread_id} - {ip_address}:{status} - {method} {path} {error}"
                        )

                        async with self._backoff_sem:
                            transport.close()

                            return
                
                        
                has_middleware = self._middleware_enabled.get(handler_key)

                await ctx.log(Event(
                    level=LogLevel.DEBUG,
                    message=f'Request - {method} {path}:{ip_address} - {"middleware found" if has_middleware else "no middleware found"}'
                ))

                args, kwargs, validation_error = fabricator.parse(
                    request_data,
                    query=query,
                    params=params,
                    has_middleware=has_middleware,
                )

                await ctx.log(Event(
                    level=LogLevel.DEBUG,
                    message=f'Request - {method} {path}:{ip_address} - parsed args'
                ))

                if validation_error:
                    await ctx.log(
                        Response(
                            path=path,
                            method=method,
                            level=LogLevel.ERROR,
                            ip_address=ip_address,
                            error=f'Rejected by request validation - {str(validation_error)}',
                            status=422
                        ),
                        template="{timestamp} - {level} - {ip_address}:{status} - {method} {path} {error}"
                    )

                    invalid_request_response = HTTPResponse(
                        path=path,
                        status=422,
                        error="Unprocessable Content",
                        data=validation_error.json(),
                        protocol=request_type,
                        method=method,
                        headers={
                            'content-type': 'application/json'
                        }
                    )

                    transport.write(invalid_request_response.prepare_response())

                    return
                

                response_headers: Dict[str, str] = self._response_headers.get(handler_key, {})
                encoded_data: str = ""

                await ctx.log(Event(
                    level=LogLevel.DEBUG,
                    message=(
                        f'Request - {method} {path}:{ip_address} - sending response headers - {', '.join(response_headers)}'
                        if len(response_headers) > 0
                        else f'Request - {method} {path}:{ip_address} - has no response headers'
                    )
                ))

                (response_parser, status_code) = self._response_parsers.get(
                    handler_key,
                    (None, None)
                )

                if status_code is None:
                    status_code = 200
                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {method} {path}:{ip_address} - set status code to default - {status_code}'
                    ))

                if has_middleware:

                    context = ResponseContext(
                        path,
                        method,
                        params,
                        query,
                        request_data,
                        args,
                        kwargs,
                        fabricator,
                        response_parser,
                        ip_address,
                    )

                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {method} {path}:{ip_address} - executing route handler with middleware - {handler.__class__.__name__}'
                    ))

                    response: Tuple[ResponseContext, Any] = await handler(context=context)

                    context, response_data = response 

                    if len(context.errors) > 0 and transport.is_closing() is False:
                        error_headers = {
                            'content-type': 'application/json'
                        }

                        errors = orjson.dumps([
                            {
                                'error': str(error),
                            } for error in context.errors
                        ])


                        middleware_error_response = HTTPResponse(
                            path=path,
                            status=500,
                            error='Internal server error.',
                            data=errors.decode(),
                            protocol=request_type,
                            headers=error_headers,
                            method=method,
                        )

                        joined_errors = ', '.join([str(error) for error in context.errors])
                        await ctx.log(
                            Response(
                                path=path,
                                method=method,
                                level=LogLevel.ERROR,
                                ip_address=ip_address,
                                error=f'Middleware encountered errors - {joined_errors}',
                                status=500
                            ),
                            template="{timestamp} - {level} - {thread_id} - {ip_address}:{status} - {method} {path} {error}"
                        )

                        transport.write(middleware_error_response.prepare_response(
                            compression=context.compressor,
                            compression_level=context.compression_level
                        ))
                    
                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {method} {path}:{ip_address} - completed  route handler execution with middleware'
                    ))

                    response_headers.update(context.response_headers)
                    status_code = context.status or status_code

                else:

                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {method} {path}:{ip_address} - executing route handler'
                    ))

                    response_data = await handler(*args, **kwargs)

                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {method} {path}:{ip_address} - completed route handler execution'
                    ))


                if response_parser:
                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {method} {path}:{ip_address} - serializing response body'
                    ))

                    encoded_data = parse_response(
                        response_data, 
                        response_parser
                    )
                    content_length = len(encoded_data)
                    headers = f"content-length: {content_length}"

                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {method} {path}:{ip_address} - serialized {content_length} bytes'
                    ))

                elif response_data:
                    encoded_data = response_data

                    content_length = len(response_data)

                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {method} {path}:{ip_address} - set response body as {content_length} bytes'
                    ))

                    headers = f"content-length: {content_length}"

                else:
                    headers = "content-length: 0"

                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {method} {path}:{ip_address} - response has no body'
                    ))

                for key in response_headers:
                    headers = f"{headers}\r\n{key}: {response_headers[key]}"

                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {method} {path}:{ip_address} - response adding header - {key}:{response_headers[key]}'
                    ))

                response_data = (
                    f"HTTP/1.1 {status_code} OK\r\n{headers}\r\n\r\n{encoded_data}".encode()
                )

                if self._use_encryption:
                    encrypted_data = self._encryptor.encrypt(response_data)
                    response_data = self._compressor.compress(encrypted_data)

                if self._use_encryption is False:
                    await ctx.log(
                        Response(
                            path=path,
                            method=method,
                            ip_address=ip_address,
                            status=status_code
                        ),
                        template="{timestamp} - {level} - {thread_id} - {ip_address}:{status} - {method} {path} - {status}"
                    )
                
                transport.write(response_data)

            except KeyError:
                if self._supported_handlers.get(path) is None:
                    not_found_response = HTTPResponse(
                        path=path,
                        status=404,
                        error="Not Found",
                        protocol=request_type,
                        method=method,
                    )

                    await ctx.log(
                        Response(
                            path=path,
                            method=method,
                            level=LogLevel.ERROR,
                            ip_address=ip_address,
                            error='Failed to match route',
                            status=404
                        ),
                        template="{timestamp} - {level} - {thread_id} - {ip_address}:{status} - {method} {path} {error}"
                    )

                    transport.write(not_found_response.prepare_response())

                elif self._supported_handlers[path].get(method) is None:
                    method_not_allowed_response = HTTPResponse(
                        path=path,
                        status=405,
                        error="Method Not Allowed",
                        protocol=request_type,
                        method=method,
                    )

                    await ctx.log(
                        Response(
                            path=path,
                            method=method,
                            level=LogLevel.ERROR,
                            ip_address=ip_address,
                            error='Failed to match allowed methods',
                            status=404
                        ),
                        template="{timestamp} - {level} - {thread_id} - {ip_address}:{status} - {method} {path} {error}"
                    )

                    transport.write(method_not_allowed_response.prepare_response())

            except Exception as e:
                async with self._backoff_sem:

                    await ctx.log(
                        Response(
                            path=path,
                            method=method,
                            level=LogLevel.ERROR,
                            ip_address=ip_address,
                            error=str(e),
                            status=500
                        ),
                        template="{timestamp} - {level} - {thread_id} - {ip_address}:{status} - {method} {path} {error}"
                    )

                    if transport.is_closing() is False:
                        server_error_respnse = HTTPResponse(
                            path=path,
                            status=500,
                            error=f"Internal Error - {str(e)}",
                            protocol=request_type,
                            headers={
                                'content-type': 'application/json'
                            },
                            method=method,
                        )

                        transport.write(server_error_respnse.prepare_response())

    async def close(self):
        await self._limiter.close()
        await super().close()

        await self._logger.log(Event(
            level=LogLevel.DEBUG,
            message=f'Closing HTTP connection at - {self.host}:{self.port}'
        ))

        await self._logger.close()
    
    def abort(self):
        self._limiter.abort()
        super().abort()

        self._logger.abort()
