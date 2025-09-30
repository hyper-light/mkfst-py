from __future__ import annotations

from http.cookies import SimpleCookie
from typing import (
    Any,
    Dict,
    List,
    Type,
)

import orjson
from pydantic import (
    BaseModel,
    StrictBool,
    StrictBytes,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

HTTPEncodable = StrictStr | StrictInt | StrictBool | StrictFloat | None


class Headers(BaseModel):
    @model_validator(mode="before")
    def validate_headers(cls, val: Type[Headers]):
        encodable_values = [
            str,
            int,
            bytes,
            bool,
            float,
            StrictStr,
            StrictInt,
            StrictBool,
            StrictFloat,
        ]

        fields = val.model_fields
        for field, value in fields.items():
            assert value.annotation in encodable_values, (
                f"Err. - field {field} must have JSON encodable type."
            )

    @classmethod
    def make(
        cls,
        model: Type[Headers],
        data: dict[bytes, bytes],
        data_line_idx: int,
    ):
        headers: Dict[str, Any] = {}
        if data_line_idx == -1:
            header_lines = data[1:]
            data_line_idx = 0

            for header_line in header_lines:
                if header_line == b"":
                    data_line_idx += 1
                    break

                key, value = header_line.decode().split(":", maxsplit=1)

                headers[key.lower().replace("-", "_")] = value.strip()

                data_line_idx += 1

            data_line_idx += 1

            return (
                model(**headers),
                data_line_idx,
                headers,
            )

        return (None, data_line_idx, headers)

    @classmethod
    def make_raw(
        cls,
        data: List[bytes],
        data_line_idx: int,
    ):
        headers: Dict[str, Any] = {}
        if data_line_idx == -1:
            header_lines = data[1:]
            data_line_idx = 0

            for header_line in header_lines:
                if header_line == b"":
                    data_line_idx += 1
                    break

                key, value = header_line.decode().split(":", maxsplit=1)

                headers[key.lower().replace("-", "_")] = value.strip()

                data_line_idx += 1

            data_line_idx += 1

            return (
                data_line_idx,
                headers,
            )

        return (data_line_idx, headers)


class Cookies(BaseModel):
    @model_validator(mode="before")
    def validate_headers(cls, val: Type[Query]):
        encodable_values = [
            str,
            int,
            bytes,
            bool,
            float,
            StrictStr,
            StrictInt,
            StrictBool,
            StrictFloat,
        ]

        fields = val.model_fields
        for field, value in fields.items():
            if field == "cookie":
                assert value.annotation == str, (
                    "Err. - field cookie must be either str or StrictStr type"
                )

            else:
                assert value.annotation in encodable_values, (
                    f"Err. - field {field} must have JSON encodable type."
                )

    @classmethod
    def make(cls, model: Type[Cookies], headers: Dict[bytes, bytes]):
        cookie_header = headers.get(b"cookie")

        if cookie_header is None:
            return model()

        parsed_cookies = SimpleCookie()
        parsed_cookies.load(cookie_header)

        return model(**{name: morsel.value for name, morsel in parsed_cookies.items()})

    @classmethod
    def make_raw(cls, headers: Dict[str, Any]):
        cookie_header: str = headers.get("cookie")

        if cookie_header is None:
            return

        parsed_cookies = SimpleCookie()
        parsed_cookies.load(cookie_header)

        return {name: morsel.value for name, morsel in parsed_cookies.items()}


class Parameters(BaseModel):
    @model_validator(mode="before")
    def validate_headers(cls, val: Type[Parameters]):
        encodable_values = [
            str,
            int,
            bytes,
            bool,
            float,
            StrictStr,
            StrictInt,
            StrictBool,
            StrictFloat,
        ]

        fields = val.model_fields
        for field, value in fields.items():
            assert value.annotation in encodable_values, (
                f"Err. - field {field} must have JSON encodable type."
            )


class Query(BaseModel):
    @model_validator(mode="before")
    def validate_headers(cls, val: Type[Query]):
        encodable_values = [
            str,
            int,
            bytes,
            bool,
            float,
            StrictStr,
            StrictInt,
            StrictBool,
            StrictFloat,
        ]

        fields = val.model_fields
        for field, value in fields.items():
            assert value.annotation in encodable_values, (
                f"Err. - field {field} must have JSON encodable type."
            )

    @classmethod
    def make(cls, model: Type[Query], query: str):
        query_params: Dict[str, str] = {}
        if len(query) < 1:
            params = query.split("&")

            for param in params:
                key, value = param.split("=")

                query_params[key] = value

        return model(**query_params)


class Body(BaseModel):
    content: StrictStr | StrictBytes

    def text(self, encoding: str = "utf-8"):
        if isinstance(self.content, bytes):
            return self.content.decode(encoding=encoding)

        return self.content

    def json(self):
        content = self.content
        if isinstance(content, bytes):
            content = self.content.decode()

        return orjson.loads(content)

    @classmethod
    def make(
        cls,
        data: List[bytes],
        data_line_idx: int,
    ):
        return Body(content=b"".join(data[data_line_idx:]).strip())

    @classmethod
    def read(
        cls,
        data: List[bytes],
        data_line_idx: int,
    ):
        if data_line_idx == -1:
            header_lines = data[1:]
            data_line_idx = 0

            headers: Dict[str, Any] = {}

            for header_line in header_lines:
                if header_line == b"":
                    data_line_idx += 1
                    break

                key, value = header_line.decode().split(":", maxsplit=1)

                headers[key.lower()] = value.strip()

                data_line_idx += 1

            data_line_idx += 1

        return b"".join(data[data_line_idx:]).strip()
