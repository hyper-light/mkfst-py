from __future__ import annotations
from urllib.parse import urlparse, ParseResult
from typing import (
    Any,
    Dict,
    List,
    Literal,
    Tuple,
    Type,
)

from mkfst.connection.tcp.fabricator import Fabricator
from mkfst.models.http.request_models import Cookies, Headers


class ResponseContext:
    __slots__ = (
        "path",
        "method",
        "params",
        "query",
        "request_headers",
        "cookies",
        "body",
        "response_headers",
        "status",
        "errors",
        "args",
        "kwargs",
        "_data",
        "fabricator",
        "parser",
        "compressor",
        "compression_level",
        "ip_address",
        "request_addr",
        "protocol",
        "upgrade_port",
    )

    def __init__(
        self,
        path: str,
        method: str,
        headers: dict[str, str],
        params: Dict[str, str] | None,
        query: str | None,
        data: List[bytes],
        args: Tuple[Any, ...],
        kwargs: Dict[str, Any],
        fabricator: Fabricator,
        parser: Type[Any],
        ip_address: str,
        protocol: Literal["https", "http", "wss", "ws"],
        request_addr: tuple[str, int],
        upgrade_port: int,
    ) -> None:
        self.ip_address = ip_address
        self.protocol = protocol
        self.path = path
        self.method = method
        self.params: Dict[str, Any] = params or {}
        self.query: str = query or ""

        self.request_headers: Dict[str, Any] = headers
        self.cookies: Dict[str, Any] = {}
        self.body: Any | None = None

        self.response_headers: Dict[str, Any] = {}
        self.status: int | None = None
        self.parser = parser
        self.errors: List[Exception] = []

        self.args = args
        self.kwargs = kwargs
        self._data = data
        self.fabricator = fabricator
        self.compressor: Literal["gzip", "zstd"] | None = None
        self.compression_level: int | None = None
        self.request_addr = request_addr
        self.upgrade_port = upgrade_port

    def update(self, context: ResponseContext):
        self.request_headers.update(context.request_headers)
        self.response_headers.update(context.response_headers)
        self.params.update(context.params)
        self.cookies.update(context.cookies)

        if context.status:
            self.status = context.status

    def to_request_url(self) -> ParseResult:
        host: str = self.request_headers.get("host")
        port: int | None = None
        if host is None:
            host, port = self.request_addr

        scheme = self.protocol

        if port:
            url = f"{scheme}://{host}:{port}"

        else:
            url = f"{scheme}://{host}"

        if self.path:
            url += self.path

        return urlparse(url)

    def get_bytes_arg(
        self,
    ) -> Tuple[bytes, int, None] | Tuple[bytes, None, int] | Tuple[bytes, None, None]:
        for arg in self.args:
            if isinstance(arg, bytes):
                return arg

        for value in self.kwargs.values():
            if isinstance(value, bytes):
                return value

        return b""

    def get_headers(self):
        if param_key := self.fabricator.param_keys.get("headers"):
            is_position = isinstance(param_key, int)
            headers: Headers = (
                self.args[param_key] if is_position else self.kwargs[param_key]
            )

            return headers

        return None

    def get_headers_and_cookies(self):
        headers: Dict[str, Any] = {}
        cookies: Dict[str, Any] = {}

        if param_key := self.fabricator.param_keys.get("headers"):
            headers: Headers = (
                self.args[param_key]
                if isinstance(param_key, int)
                else self.kwargs[param_key]
            )

        elif param_key := self.fabricator.param_keys.get("cookies"):
            cookies: Cookies = (
                self.args[param_key]
                if isinstance(param_key, int)
                else self.kwargs[param_key]
            )

        headers_content: Dict[str, str] = {}
        cookies_content: Dict[str, str] = {}
        if headers:
            headers_content = headers.model_dump()

        if headers and cookies is None:
            cookies_content = Cookies.make_raw(headers)

        elif cookies:
            cookies_content = cookies.model_dump()

        return (
            headers_content,
            cookies_content,
        )

    def update_request_headers(self, new_headers: Dict[str, Any]):
        self.request_headers.update(new_headers)

        headers = self.get_headers()

        updated_headers: Headers | None = None

        if headers:
            headers_dict = headers.model_dump()

            headers_dict.update(self.request_headers)

            updated_headers = headers.model_copy(headers_dict)

        param_key = self.fabricator.param_keys.get("headers")
        is_position = isinstance(param_key, int)

        if updated_headers and param_key and is_position:
            self.args[param_key] = updated_headers

        elif updated_headers and param_key:
            self.kwargs[param_key] = updated_headers

    def update_request_data(self, data: Any):
        body_key = self.fabricator.param_keys.get("body")
        is_position = isinstance(body_key, int)

        if body_key and is_position:
            self.args[body_key] = data

        elif body_key:
            self.kwargs[body_key] = data
