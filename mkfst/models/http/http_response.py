from __future__ import annotations
import msgspec
from base64 import b64encode
from gzip import compress as gzip_compress
from typing import Dict, Literal, Optional

import hyperjson
from zstandard import compress as zstd_compress

from .model import Model


class HTTPResponse(msgspec.Struct, kw_only=True):
    protocol: str = "HTTP/1.1"
    path: Optional[str] = None
    error: Optional[str] = None
    method: Optional[
        Literal["GET", "POST", "HEAD", "OPTIONS", "PUT", "PATCH", "DELETE"]
    ] = None
    status: Optional[int] = None
    status_message: Optional[str] = None
    params: Dict[str, str] = {}
    headers: Dict[str, str] = {}
    data: Optional[str | Model] = None

    def prepare_response(
        self,
        compression: Literal["gzip", "zstd"] | None = None,
        compression_level: int | None = None,
    ):
        message = "OK"
        if self.error:
            message = self.error

        head_line = f"HTTP/1.1 {self.status} {message}"

        encoded_data: str = ""

        if isinstance(self.data, Model) or self.data in Model.__subclasses__():
            encoded_data = hyperjson.dumps(msgspec.structs.asdict(self.data)).decode()
            content_length = len(encoded_data)
            headers = f"content-length: {content_length}"

        elif isinstance(self.data, (dict, list)):
            encoded_data = hyperjson.dumps(self.data).decode()
            content_length = len(encoded_data)
            headers = f"content-length: {content_length}"

        elif self.data:
            encoded_data = self.data

            content_length = len(encoded_data)
            headers = f"content-length: {content_length}"

        else:
            headers = "content-length: 0"

        if compression == "gzip":
            encoded_data = b64encode(
                gzip_compress(encoded_data.encode(), compresslevel=compression_level)
            ).decode()

            headers = f"{headers}\r\nx-compression-encoding: {compression}"
            content_length = len(encoded_data)
            headers = f"content-length: {content_length}"

        elif compression == "zstd":
            encoded_data = b64encode(
                zstd_compress(encoded_data.encode(), level=compression_level)
            ).decode()

            headers = f"{headers}\r\nx-compression-encoding: {compression}"
            content_length = len(encoded_data)
            headers = f"content-length: {content_length}"

        response_headers = self.headers
        if response_headers:
            for key in response_headers:
                headers = f"{headers}\r\n{key}: {response_headers[key]}"

        return f"{head_line}\r\n{headers}\r\n\r\n{encoded_data}".encode()
