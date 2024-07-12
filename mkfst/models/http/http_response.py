import inspect
from base64 import b64encode
from gzip import compress as gzip_compress
from typing import Dict, Literal, Optional, Union

import orjson
from pydantic import BaseModel, Json, StrictInt, StrictStr
from zstandard import compress as zstd_compress

from mkfst.models.base.message import Message


class HTTPResponse(BaseModel):
    protocol: StrictStr = "HTTP/1.1"
    path: Optional[StrictStr] = None
    error: Optional[StrictStr] = None
    method: Optional[
        Literal["GET", "POST", "HEAD", "OPTIONS", "PUT", "PATCH", "DELETE"]
    ]=None
    status: Optional[StrictInt] = None
    status_message: Optional[StrictStr] = None
    params: Dict[StrictStr, StrictStr] = {}
    headers: Dict[StrictStr, StrictStr] = {}
    data: Optional[Union[Json, StrictStr]] = None

    def prepare_response(
        self,
        compression: Literal['gzip', 'zstd'] | None = None,
        compression_level: int | None = None
    ):
        message = "OK"
        if self.error:
            message = self.error

        head_line = f"HTTP/1.1 {self.status} {message}"

        encoded_data: str = ""

        if isinstance(self.data, Message):
            encoded_data = orjson.dumps(self.data.to_data()).decode()

            content_length = len(encoded_data)
            headers = f"content-length: {content_length}"

        elif inspect.isclass(self.data) and issubclass(self.data, BaseModel):
            encoded_data = orjson.dumps(self.data.model_dump()).decode()
            content_length = len(encoded_data)
            headers = f"content-length: {content_length}"

        elif isinstance(self.data, (dict, list)):
            encoded_data = orjson.dumps(self.data).decode()
            content_length = len(encoded_data)
            headers = f"content-length: {content_length}"

        elif self.data:
            encoded_data = self.data

            content_length = len(encoded_data)
            headers = f"content-length: {content_length}"

        else:
            headers = "content-length: 0"

        if compression == 'gzip':
            encoded_data = b64encode(
                gzip_compress(
                    encoded_data.encode(), 
                    compresslevel=compression_level
                )
            ).decode()
            
            headers = f"{headers}\r\nx-compression-encoding: {compression}"
            content_length = len(encoded_data)
            headers = f"content-length: {content_length}"

        elif compression == 'zstd':
            encoded_data = b64encode(
                zstd_compress(
                    encoded_data.encode(),
                    level=compression_level
                )
            ).decode()

            headers = f"{headers}\r\nx-compression-encoding: {compression}"
            content_length = len(encoded_data)
            headers = f"content-length: {content_length}"


        response_headers = self.headers
        if response_headers:
            for key in response_headers:
                headers = f"{headers}\r\n{key}: {response_headers[key]}"

        return f"{head_line}\r\n{headers}\r\n\r\n{encoded_data}".encode()
