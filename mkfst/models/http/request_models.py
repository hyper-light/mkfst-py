from __future__ import annotations
import msgspec
from http.cookies import SimpleCookie
from typing import (
    Any,
    Dict,
    List,
    Type,
    TypeVar,
)

import hyperjson
from pydantic import (
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
)
from .model import Model

HTTPEncodable = StrictStr | StrictInt | StrictBool | StrictFloat | None

T = TypeVar("t")


class Headers(Model):
    @classmethod
    def make(cls, model: type[Headers], headers: dict[str, str]):
        return model(**headers)

    @classmethod
    def make_raw(cls, headers: dict[str, str]):
        return headers


class Cookies(Model):
    @classmethod
    def make(cls, model: Type[Cookies], headers: Dict[str, str]):
        cookie_header = headers.get("cookie")

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


class Parameters(Model):
    @classmethod
    def make(cls, model: type[Parameters], params: dict[str, str]):
        return model(**params)

    @classmethod
    def make_raw(cls, params: dict[str, str]):
        return params


class Query(Model):
    @classmethod
    def make(cls, model: Type[Query], query: str):
        query_params: Dict[str, str] = {}
        if len(query) < 1:
            params = query.split("&")

            for param in params:
                key, value = param.split("=")

                query_params[key] = value

        return model(**query_params)

    @classmethod
    def make_raw(cls, query: str):
        query_params: Dict[str, str] = {}
        if len(query) < 1:
            params = query.split("&")

            for param in params:
                key, value = param.split("=")

                query_params[key] = value

        return query_params


class Body(Model):
    content: bytes

    def text(self, encoding: str = "utf-8"):
        return self.content.decode(encoding=encoding)

    def json(self):
        return hyperjson.loads(self.content)

    @classmethod
    def make(
        cls,
        data: bytes,
    ):
        return Body(content=data)

    @classmethod
    def make_raw(cls, data: bytes):
        return data
