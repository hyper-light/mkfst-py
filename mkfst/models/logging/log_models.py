from typing import Any, Dict, Literal

from mkfst.logging import Entry, LogLevel

JSONEncodableValue = str | int | bool | float | None


class Event(Entry, kw_only=True):
    message: str | bytes | None = None
    level: LogLevel = LogLevel.INFO

    def to_template(self, template: str, context=None):
        kwargs: dict[
            str,
            int | str | bool | float | LogLevel | list | dict | set | Any,
        ] = {field: getattr(self, field) for field in self.__struct_fields__}

        if isinstance(self.message, bytes):
            kwargs["message"] = self.message.decode()

        kwargs["level"] = kwargs["level"].value

        if context:
            kwargs.update(context)

        return template.format(**kwargs)


class Request(Entry, kw_only=True):
    level: LogLevel = LogLevel.INFO
    message: str | bytes | None = None
    path: str | bytes | None = None
    protocol: Literal["HTTP/1.1"] | Literal[b"HTTP/1.1"] = "HTTP/1.1"
    method: str | bytes | None = None
    headers: Dict[str, JSONEncodableValue] | dict[bytes, bytes] | None = None
    params: Dict[str, JSONEncodableValue] | dict[bytes, bytes] | None = None
    query: str | bytes | None = None
    body: str | bytes | None = None
    error: Exception | str | None = None
    ip_address: str | None = None

    def to_template(
        self,
        template: str,
        context: Dict[str, Any] | None = None,
    ):
        kwargs = {
            "level": self.level.value,
            "path": self.path
            if isinstance(self.path, str) or self.path is None
            else self.path.decode(),
            "method": self.method
            if isinstance(self.method, str) or self.method is None
            else self.method.decode(),
            "headers": ", ".join(
                [
                    f"{key}:{header}"
                    if isinstance(key, str) and isinstance(header, str)
                    else f"{key.decode()}:{header.decode()}"
                    for key, header in self.headers.items()
                ]
            )
            if self.headers
            else None,
            "params": ", ".join(
                [
                    f"{key}:{param}"
                    if isinstance(key, str) and isinstance(param, str)
                    else f"{key.decode()}:{param.decode()}"
                    for key, param in self.params.items()
                ]
            )
            if self.params
            else None,
            "query": self.query
            if isinstance(self.query, str) or self.query is None
            else self.query.decode(),
            "body": self.body,
            "error": self.error,
            "ip_address": self.ip_address,
        }

        if isinstance(self.message, bytes):
            kwargs["message"] = self.message.decode()

        elif self.message:
            kwargs["message"] = self.message

        if context:
            kwargs.update(context)

        return template.format(**kwargs)


class Response(Entry, kw_only=True):
    level: LogLevel = LogLevel.INFO
    message: str | bytes | None = None
    path: str | bytes | None = None
    protocol: Literal["HTTP/1.1"] | Literal[b"HTTP/1.1"] = "HTTP/1.1"
    method: str | bytes | None = None
    error: Exception | str | None = None
    ip_address: str | None = None
    status: int | None = None

    def to_template(
        self,
        template: str,
        context: Dict[str, Any] | None = None,
    ):
        kwargs: Dict[
            str,
            int | str | bool | float | LogLevel | list | dict | set | Any,
        ] = {
            field: getattr(self, field)
            for field in self.__struct_fields__
            if getattr(self, field) is not None
        }

        if isinstance(self.path, bytes):
            kwargs["path"] = self.path.decode()

        if isinstance(self.protocol, bytes):
            kwargs["protocol"] = self.protocol.decode()

        if isinstance(self.method, bytes):
            kwargs["method"] = self.method.decode()

        if isinstance(self.message, bytes):
            kwargs["message"] = self.message.decode()

        kwargs["level"] = kwargs["level"].value

        if context:
            kwargs.update(context)

        return template.format(**kwargs)
