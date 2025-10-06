from __future__ import annotations

import asyncio
import ipaddress
import re
import functools
import socket
from collections import defaultdict, deque
from functools import lru_cache
from typing import (
    Any,
    Callable,
    Deque,
    Dict,
    List,
    Literal,
    Optional,
    Tuple,
    Union,
    Iterable,
)

import orjson
import psutil

from mkfst.connection.base.connection_type import ConnectionType
from mkfst.env import Env
from mkfst.logging import Logger, LogLevel
from mkfst.middleware.base.response_context import ResponseContext
from mkfst.models.http import (
    HTTPResponse,
    parse_response,
    Model,
)
from mkfst.models.logging import Event, Response, Request
from mkfst.rate_limiting import Limiter

from .fabricator import Fabricator
from .mercury_sync_tcp_connection import MercurySyncTCPConnection
from .protocols.receive_buffer import ReceiveBuffer
from .protocols.patterns import (
    request_line,
    header_field,
    request_target,
    method as method_re,
)
from .router import Router
from .request_state import RequestState
from .protocols.validate import validate

Handler = Callable[..., Tuple[Any, int]]


request_line_re = re.compile(request_line.encode("ascii"))
header_field_re = re.compile(header_field.encode("ascii"))
method_re = re.compile(method_re.encode("ascii"))
request_target_re = re.compile(request_target.encode("ascii"))

obs_fold_re = re.compile(rb"[ \t]+")


def _obsolete_line_fold(lines: Iterable[bytes]) -> Iterable[bytes]:
    it = iter(lines)
    last: Optional[bytes] = None
    for line in it:
        match = obs_fold_re.match(line)
        if match:
            if last is None:
                raise Exception("continuation line at start of headers")
            if not isinstance(last, bytearray):
                # Cast to a mutable type, avoiding copy on append to ensure O(n) time
                last = bytearray(last)
            last += b" "
            last += line[match.end() :]
        else:
            if last is not None:
                yield last
            last = line
    if last is not None:
        yield last


class MercurySyncHTTPConnection(MercurySyncTCPConnection):
    def __init__(
        self,
        host: str,
        port: int,
        instance_id: int,
        env: Env,
        upgrade_port: int | None = None,
    ) -> None:
        super().__init__(host, port, instance_id, env)

        self.env = env
        self._waiters: dict[str, asyncio.Future] = defaultdict(asyncio.Future)
        self._connections: Dict[str, List[asyncio.Transport]] = defaultdict(list)
        self._http_socket: Union[socket.socket, None] = None
        self._hostnames: Dict[Tuple[str, int], str] = {}
        self._max_concurrency = env.MERCURY_SYNC_MAX_CONCURRENCY

        self.connection_type = ConnectionType.HTTP
        self._is_server = env.MERCURY_SYNC_USE_HTTP_SERVER
        self._use_encryption = env.MERCURY_SYNC_USE_HTTP_MSYNC_ENCRYPTION

        self._supported_handlers: Dict[str, Dict[str, str]] = defaultdict(dict)
        self._response_parsers: Dict[Model, Tuple[Callable[[Any], str], int]] = {}
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
        self._cache: dict[bytes, tuple[bytes, int, float]] = {}
        self._max_request_cache_size = env.MERCURY_SYNC_MAX_REQUEST_CACHE_SIZE
        self._cache_purge_lock: asyncio.Lock | None = None
        self._request_caching_enabled = env.MERCURY_SYNC_ENABLE_REQUEST_CACHING
        self._verify_cert = env.MERCURY_SYNC_VERIFY_SSL_CERT
        self._upgrade_port = upgrade_port
        self.waiting_for_data: asyncio.Event = asyncio.Event()
        self._runner_task: asyncio.Task | None = None

    def from_env(self, env: Env):
        super().from_env(env)

        self._max_concurrency = env.MERCURY_SYNC_MAX_CONCURRENCY
        self._is_server = env.MERCURY_SYNC_USE_HTTP_SERVER
        self._use_encryption = env.MERCURY_SYNC_USE_HTTP_MSYNC_ENCRYPTION
        rate_limit_strategy = env.MERCURY_SYNC_HTTP_RATE_LIMIT_STRATEGY
        self._rate_limiting_enabled = rate_limit_strategy != "none"
        self._rate_limiting_backoff_rate = env.MERCURY_SYNC_HTTP_RATE_LIMIT_BACKOFF_RATE
        self._max_request_cache_size = env.MERCURY_SYNC_MAX_REQUEST_CACHE_SIZE
        self._request_caching_enabled = env.MERCURY_SYNC_ENABLE_REQUEST_CACHING
        self._verify_cert = env.MERCURY_SYNC_VERIFY_SSL_CERT

    async def connect_async(
        self,
        cert_path: Optional[str] = None,
        key_path: Optional[str] = None,
        worker_socket: Optional[socket.socket] = None,
        upgrade_socket: Optional[socket.socket] = None,
    ):
        async with self._logger.context() as ctx:
            self._backoff_sem = asyncio.Semaphore(self._rate_limiting_backoff_rate)

            await ctx.log(
                Event(
                    level=LogLevel.DEBUG,
                    message=f"Starting HTTP connection on - {self.host}:{self.port}",
                )
            )

            if self._request_caching_enabled:
                self._cache_purge_lock = asyncio.Lock()

            return await super().connect_async(
                cert_path=cert_path,
                key_path=key_path,
                worker_socket=worker_socket,
                upgrade_socket=upgrade_socket
                if upgrade_socket and cert_path and key_path
                else None,
            )

    def read(
        self,
        data: ReceiveBuffer,
        transport: asyncio.Transport,
        data_ready: asyncio.Future,
    ) -> None:
        self._pending_responses.append(
            asyncio.create_task(
                self._execute(
                    data,
                    transport,
                    data_ready,
                )
            )
        )

    async def _parse(
        self,
        transport: asyncio.Transport,
        data: ReceiveBuffer,
        data_ready: asyncio.Future,
    ):
        async with self._logger.context() as ctx:
            request_method: bytes | str | None = None
            request_path: bytes | str | None = None
            request_version: bytes | str | None = None
            request_headers: dict[str, str] = {}
            request_data: bytes | None = None
            request_query: str | None = None

            ip_address, _ = transport.get_extra_info("peername")

            try:
                if self._use_encryption:
                    encrypted_data = self._encryptor.decrypt(data)
                    data = self._decompressor.decompress(encrypted_data)

                lines = data.maybe_extract_lines()
                if lines is None and data.is_next_line_obviously_invalid_request_line():
                    raise Exception("Bad request line")

                elif lines is None:
                    raise Exception("No lines received")

                if not lines:
                    raise Exception("Request empty")

                matches = validate(
                    request_line_re, lines[0], "illegal request line: {!r}", lines[0]
                )

                request_headers = {
                    matches["field_name"].decode(): matches["field_value"].decode()
                    for matches in [
                        validate(
                            header_field_re, line, "illegal header line: {!r}", line
                        )
                        for line in _obsolete_line_fold(lines[1:])
                    ]
                }

                if (request_headers.get("Host", "") is None) and (
                    request_headers.get("host") is None
                ):
                    raise Exception("Missing Host header")

                request_method = matches.get("method", b"")
                request_version = matches.get("version", b"HTTP/1.1")
                request_path = matches.get("target", b"")

                request_method = request_method.decode()
                request_version = request_version.decode()
                request_path = request_path.decode()

                request_query: Union[str, None] = None
                if "?" in request_path:
                    request_path, request_query = request_path.split("?")

                request_data = b""
                if (
                    (expect_header := request_headers.get("Expect"))
                    and expect_header.lower() == "100-continue"
                    and transport.is_closing() is False
                ):
                    server_error_respnse = HTTPResponse(
                        status=100,
                        protocol="HTTP/1.1",
                        headers=self._response_headers.get(
                            f"{request_method}_{request_path}", {}
                        ),
                        path=request_path,
                        status_message="Continue",
                    )

                    transport.write(server_error_respnse.prepare_response())

                    self.waiting_for_data.set()
                    data = await asyncio.wait_for(
                        data_ready,
                        timeout=self._request_timeout,
                    )

                    request_data += data.read_all()
                    self.waiting_for_data.clear()

                if request_headers.get("Transfer-Encoding") or request_headers.get(
                    "transfer-encoding",
                ):
                    next_line = bytes(data.maybe_extract_next_line() or b"")
                    chunk_size = int(next_line.rstrip(), 16)

                    while next_line := data.maybe_extract_at_most(chunk_size + 2):
                        next_line = (next_line or b"").rstrip()
                        request_data += next_line

                        chunk_size = int(bytes(data.buffer.rstrip()), 16)

                        if not chunk_size:
                            break

                        self.waiting_for_data.set()
                        data = await asyncio.wait_for(
                            data_ready,
                            timeout=self._request_timeout,
                        )

                        request_data += data.read_all()
                        self.waiting_for_data.clear()

                elif (content_length := request_headers.get("Content-Length")) or (
                    content_length := request_headers.get("content-length")
                ):
                    content_length_amount = int(content_length)

                    request_data += (
                        data.maybe_extract_at_most(content_length_amount + 1) or b""
                    )

                elif request_method in ["POST", "PUT", "PATCH"]:
                    raise Exception(
                        "No Content-Length or Transfer-Encoding header supplied"
                    )

                data.clear()
                await ctx.log(
                    Request(
                        level=LogLevel.DEBUG,
                        message="Request received",
                        path=request_path,
                        method=request_method,
                        ip_address=ip_address,
                    )
                )

                return (
                    RequestState.ROUTE,
                    (
                        request_path,
                        request_version,
                        request_method,
                        request_headers,
                        request_query,
                        request_data,
                        ip_address,
                    ),
                )

            except (asyncio.TimeoutError, Exception) as error:
                request_status = 400
                request_error = f"Bad Request - {str(error)}"
                if isinstance(error, asyncio.TimeoutError):
                    request_status = 408
                    request_error = (
                        f"Request exceeded timeout of {self._request_timeout} seconds"
                    )

                if isinstance(request_path, bytes):
                    request_path = request_path.decode()

                if isinstance(request_version, bytes):
                    request_version = request_version.decode()

                if isinstance(request_method, bytes):
                    request_method = request_method.decode()

                return (
                    RequestState.ERROR,
                    (
                        request_path,
                        request_version,
                        request_method,
                        request_headers,
                        request_error,
                        [{"error": request_error}],
                        request_status,
                        ip_address,
                    ),
                )

    def _route(
        self,
        request_path: str,
        request_version: str,
        request_method: str,
        request_headers: dict[str, str],
        request_query: str | None,
        request_data: bytes,
        ip_address: str,
    ):
        handler_key = f"{request_method}_{request_path}"

        handler: Handler | None = None
        fabricator: Fabricator | None = None
        request_params: Dict[str, str | Tuple[str]] | None = None

        try:
            handler = self.events[handler_key]
            fabricator = self.fabricators[handler_key]

        except KeyError:
            # Fallback to Trie router
            if match := self.routes.match(request_path):
                methods_conifg: Dict[
                    str, Dict[Literal["model", "handler"], Handler | Any]
                ] = match.anything

                request_path = match.route
                handler = methods_conifg.get(request_method)
                handler_key = f"{request_method}_{request_path}"
                request_params = match.params
                fabricator = self.fabricators.get(handler_key)

        if handler is None:
            return (
                RequestState.ERROR,
                (
                    request_path,
                    request_version,
                    request_method,
                    request_headers,
                    "Failed to match route",
                    [{"error": f"No route matching {request_path}"}],
                    404,
                    ip_address,
                ),
            )

        elif fabricator is None:
            return (
                RequestState.ERROR,
                (
                    request_path,
                    request_version,
                    request_method,
                    request_headers,
                    "Failed to match route",
                    [
                        {
                            "error": f"No route matching {request_path} for method {request_method} found"
                        }
                    ],
                    405,
                    ip_address,
                ),
            )

        has_middleware = self._middleware_enabled.get(handler_key)

        args, kwargs, validation_error = fabricator.parse(
            request_data,
            request_headers=request_headers,
            request_query=request_query,
            request_params=request_params,
            has_middleware=has_middleware,
        )

        if validation_error:
            return (
                RequestState.ERROR,
                (
                    request_path,
                    request_version,
                    request_method,
                    request_headers,
                    "Unprocessable Content",
                    [
                        {
                            "error": str(validation_error),
                        }
                    ],
                    422,
                    ip_address,
                ),
            )

        next_state = (
            request_path,
            request_version,
            request_method,
            request_headers,
            request_query,
            request_params,
            request_data,
            handler_key,
            handler,
            fabricator,
            args,
            kwargs,
            ip_address,
        )

        if self._rate_limiting_enabled:
            return (
                RequestState.RATE_LIMIT,
                next_state,
            )

        elif has_middleware:
            return (
                RequestState.MIDDLEWARE,
                next_state,
            )

        return (
            RequestState.HANDLE,
            (
                request_path,
                request_version,
                request_method,
                handler_key,
                handler,
                args,
                kwargs,
                ip_address,
            ),
        )

    async def _rate_limit(
        self,
        transport: asyncio.Transport,
        request_path: str,
        request_version: str,
        request_method: str,
        request_headers: dict[str, str],
        request_query: str | None,
        request_params: dict[str, str] | None,
        request_data: bytes,
        handler_key: str,
        handler: Callable[..., Any],
        fabricator: Fabricator,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        ip_address: str,
    ):
        async with self._logger.context() as ctx:
            try:
                await ctx.log(
                    Request(
                        level=LogLevel.DEBUG,
                        message="Entered rate limiting",
                        method=request_method,
                        path=request_path,
                        ip_address=ip_address,
                    ),
                )

                rejected = await self._limiter.limit(
                    ipaddress.ip_address(ip_address),
                    request_path,
                    request_method,
                    limit=handler.limit,
                )

                next_state = (
                    request_path,
                    request_version,
                    request_method,
                    request_headers,
                    request_query,
                    request_params,
                    request_data,
                    handler_key,
                    handler,
                    fabricator,
                    args,
                    kwargs,
                    ip_address,
                )

                await ctx.log(
                    Request(
                        level=LogLevel.DEBUG,
                        message=f"Rate limiting returned status - {rejected}",
                        method=request_method,
                        path=request_path,
                        ip_address=ip_address,
                    ),
                )

                if rejected and transport.is_closing() is False:
                    return (
                        RequestState.ABORTED,
                        (
                            request_path,
                            request_method,
                            "Too May Requests",
                            [
                                {
                                    "error": "Rejected by rate limiting and transport closed - aborting request",
                                }
                            ],
                            429,
                            ip_address,
                        ),
                    )

                elif rejected:
                    return (
                        RequestState.ABORTED,
                        (
                            request_path,
                            request_method,
                            "Too Many Requests",
                            [{"error": "Rejected by rate limiting"}],
                            429,
                            ip_address,
                        ),
                    )

                elif self._middleware_enabled.get(handler_key):
                    await ctx.log(
                        Request(
                            level=LogLevel.DEBUG,
                            message="Middleware found",
                            method=request_method,
                            path=request_path,
                            ip_address=ip_address,
                        ),
                    )

                    return (
                        RequestState.MIDDLEWARE,
                        next_state,
                    )

                return (
                    RequestState.HANDLE,
                    next_state,
                )

            except Exception as error:
                return (
                    RequestState.ERROR,
                    (
                        request_path,
                        request_version,
                        request_method,
                        request_headers,
                        "Internal Error",
                        [
                            {
                                "error": str(error),
                            }
                        ],
                        500,
                        ip_address,
                    ),
                )

    async def _run_middleware(
        self,
        transport: asyncio.Transport,
        request_path: str,
        request_version: str,
        request_method: str,
        request_headers: dict[str, str],
        request_query: str | None,
        request_params: dict[str, str] | None,
        request_data: bytes,
        handler_key: str,
        handler: Callable[..., Any],
        fabricator: Fabricator,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        ip_address: str,
    ):
        async with self._logger.context() as ctx:
            try:
                (response_parser, status_code) = self._response_parsers.get(
                    handler_key, (None, None)
                )

                if status_code is None:
                    status_code = 200
                    await ctx.log(
                        Request(
                            level=LogLevel.DEBUG,
                            message=f"Set status code to default - {status_code}",
                            method=request_method,
                            path=request_path,
                            ip_address=ip_address,
                        ),
                    )

                context = ResponseContext(
                    request_path,
                    request_method,
                    request_headers,
                    request_params,
                    request_query,
                    request_data,
                    args,
                    kwargs,
                    fabricator,
                    response_parser,
                    ip_address,
                    "https" if bool(transport.get_extra_info("sslcontext")) else "http",
                    transport.get_extra_info("sockname"),
                    self._upgrade_port,
                )

                await ctx.log(
                    Request(
                        level=LogLevel.DEBUG,
                        message=f"Executing route handler with middleware - {handler.__class__.__name__}",
                        method=request_method,
                        path=request_path,
                        ip_address=ip_address,
                    ),
                )

                response: Tuple[ResponseContext, Any] = await handler(context=context)

                context, response_data = response

                response_headers: Dict[str, str] = self._response_headers.get(
                    handler_key, {}
                )
                response_headers.update(context.response_headers)
                response_status = context.status

                if len(context.errors) > 0 and transport.is_closing() is False:
                    return (
                        RequestState.ERROR,
                        (
                            request_path,
                            request_version,
                            request_method,
                            {
                                "content-type": "application/json",
                            },
                            "Bad Request" if response_status else "Internal Error",
                            [
                                {
                                    "error": str(error),
                                }
                                for error in context.errors
                            ],
                            response_status or 500,
                            ip_address,
                        ),
                    )

                await ctx.log(
                    Request(
                        level=LogLevel.DEBUG,
                        message="Completed route handler execution with middleware",
                        method=request_method,
                        path=request_path,
                        ip_address=ip_address,
                    ),
                )

                return (
                    RequestState.COMPLETE,
                    (
                        request_path,
                        request_version,
                        request_method,
                        response_parser,
                        response_data,
                        response_headers,
                        status_code,
                        ip_address,
                    ),
                )

            except Exception as error:
                return (
                    RequestState.ERROR,
                    (
                        request_path,
                        request_version,
                        request_method,
                        request_headers,
                        "Internal Error",
                        [
                            {
                                "error": str(error),
                            }
                        ],
                        500,
                        ip_address,
                    ),
                )

    async def _handle(
        self,
        request_path: str,
        request_version: str,
        request_method: str,
        handler_key: str,
        handler: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        ip_address: str,
    ):
        async with self._logger.context() as ctx:
            response_headers: Dict[str, str] = self._response_headers.get(
                handler_key, {}
            )

            try:
                await ctx.log(
                    Request(
                        level=LogLevel.DEBUG,
                        message="Executing route handler",
                        method=request_method,
                        path=request_path,
                        ip_address=ip_address,
                    ),
                )

                response_data = await handler(*args, **kwargs)

                await ctx.log(
                    Request(
                        level=LogLevel.DEBUG,
                        message="Completed route handler execution",
                        method=request_method,
                        path=request_path,
                        ip_address=ip_address,
                    ),
                )

                (response_parser, status_code) = self._response_parsers.get(
                    handler_key, (None, None)
                )

                if status_code is None:
                    status_code = 200
                    await ctx.log(
                        Request(
                            level=LogLevel.DEBUG,
                            message=f"Set status code to default - {status_code}",
                            method=request_method,
                            path=request_path,
                            ip_address=ip_address,
                        ),
                    )

                (response_parser, status_code) = self._response_parsers.get(
                    handler_key, (None, None)
                )

                return (
                    RequestState.COMPLETE,
                    (
                        request_path,
                        request_version,
                        request_method,
                        response_parser,
                        response_data,
                        response_headers,
                        status_code,
                        ip_address,
                    ),
                )

            except Exception as error:
                return (
                    RequestState.ERROR,
                    (
                        request_path,
                        request_version,
                        request_method,
                        response_headers,
                        "Internal Error",
                        [
                            {
                                "error": str(error),
                            }
                        ],
                        500,
                        ip_address,
                    ),
                )

    def _complete_request(
        self,
        transport: asyncio.Transport,
        request_path: str,
        request_version: str,
        request_method: str,
        response_parser: Callable[..., str] | None,
        response_data: str | None,
        response_headers: dict[str, str],
        response_status_code: int,
        ip_address: str,
    ):
        try:
            encoded_data: str = ""
            if response_parser:
                encoded_data = parse_response(response_data, response_parser)
                content_length = len(encoded_data)
                headers = f"content-length: {content_length}"

            elif response_data:
                encoded_data = response_data

                content_length = len(response_data)
                headers = f"content-length: {content_length}"

            else:
                headers = "content-length: 0"

            for key in response_headers:
                headers = f"{headers}\r\n{key}: {response_headers[key]}"

            response_data = f"HTTP/1.1 {response_status_code} OK\r\n{headers}\r\n\r\n{encoded_data}".encode()

            if self._use_encryption:
                encrypted_data = self._encryptor.encrypt(response_data)
                response_data = self._compressor.compress(encrypted_data)

            transport.write(response_data)

            return (None, ())

        except Exception as error:
            return (
                RequestState.ERROR,
                (
                    request_path,
                    request_version,
                    request_method,
                    response_headers,
                    "Internal Error",
                    [
                        {
                            "error": str(error),
                        }
                    ],
                    500,
                    ip_address,
                ),
            )

    async def _execute(
        self,
        data: ReceiveBuffer,
        transport: asyncio.Transport,
        data_ready: asyncio.Future,
    ):
        status, args = await self._parse(
            transport,
            data,
            data_ready,
        )

        try:
            while True:
                match status:
                    case RequestState.ROUTE:
                        status, args = self._route(*args)

                    case RequestState.RATE_LIMIT:
                        status, args = await self._rate_limit(transport, *args)

                    case RequestState.MIDDLEWARE:
                        status, args = await self._run_middleware(transport, *args)

                    case RequestState.HANDLE:
                        status, args = await self._handle(*args)

                    case RequestState.ERROR:
                        await self._handle_error(transport, *args)

                        break

                    case RequestState.COMPLETE:
                        status, args = self._complete_request(transport, *args)

                        break

                    case RequestState.ABORTED:
                        await self._abort_request(transport, *args)

                        break

        except Exception as error:
            error_message = str(error)

            ip_address, _ = transport.get_extra_info("peername")

            await self._handle_error(
                transport,
                None,
                None,
                None,
                None,
                error_message,
                [
                    {
                        "error": error_message,
                    },
                ],
                500,
                ip_address,
            )

    async def _handle_error(
        self,
        transport: asyncio.Transport,
        request_path: str | None,
        request_version: str | None,
        request_method: str | None,
        request_headers: dict[str, str] | None,
        request_error: str,
        request_data: list[dict[Literal["error"], str]],
        request_status: int,
        ip_address: str,
    ):
        async with self._logger.context() as ctx:
            async with self._backoff_sem:
                await ctx.log(
                    Response(
                        path=request_path,
                        method=request_method,
                        level=LogLevel.ERROR,
                        ip_address=ip_address,
                        error=request_error,
                        status=request_status,
                    ),
                    template="{timestamp} - {level} - {thread_id} - {ip_address}:{status} - {method} {path} {error}",
                )

                if transport.is_closing() is False:
                    server_error_respnse = HTTPResponse(
                        path=request_path,
                        status=request_status,
                        error=request_error,
                        protocol=request_version,
                        headers=request_headers,
                        method=request_method,
                        data=orjson.dumps(request_data),
                    )

                    transport.write(server_error_respnse.prepare_response())

    async def _abort_request(
        self,
        transport: asyncio.Transport,
        request_path: str | None,
        request_method: str | None,
        request_error: str,
        request_status: int,
        ip_address: str,
    ):
        async with self._logger.context() as ctx:
            async with self._backoff_sem:
                await ctx.log(
                    Response(
                        path=request_path,
                        method=request_method,
                        level=LogLevel.ERROR,
                        ip_address=ip_address,
                        error=request_error,
                        status=request_status,
                    ),
                    template="{timestamp} - {level} - {thread_id} - {ip_address}:{status} - {method} {path} {error}",
                )

                transport.close()

    async def close(self):
        await self._limiter.close()
        await super().close()

        await self._logger.log(
            Event(
                level=LogLevel.DEBUG,
                message=f"Closing HTTP connection at - {self.host}:{self.port}",
            )
        )

        await self._logger.close()

    def abort(self):
        self._limiter.abort()
        super().abort()

        self._logger.abort()
