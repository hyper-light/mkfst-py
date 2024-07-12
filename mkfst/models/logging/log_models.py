from typing import Any, Dict, Literal

from mkfst.logging import Entry, LogLevel

JSONEncodableValue = str | int | bool | float | None

class Event(Entry, kw_only=True):
    level: LogLevel = LogLevel.INFO


class Request(Entry, kw_only=True):
    level: LogLevel = LogLevel.INFO
    path: str | None = None
    protocol: Literal['HTTP/1.1']='HTTP/1.1'
    method: str | None = None
    headers: Dict[str, JSONEncodableValue] = None
    params: Dict[str, JSONEncodableValue] = None
    query: str | None = None
    body: str | bytes | None = None
    error: Exception | str | None = None
    ip_address: str | None = None

    def to_template(
        self,
        template: str,
        context: Dict[str, Any] | None = None,
    ):

        kwargs = {
            'level': self.level.value,
            'path': self.path,
            'method': self.method,
            'headers': ', '.join([
                f'{key}:{header}' for key, header in self.headers.items()
            ]),
            'params': ', '.join([
                f'{key}:{header}' for key, header in self.headers.items()
            ]),
            'query': self.query,
            'body': self.body,
            'error': self.error,
            'ip_address': self.ip_address,
        }

        if context:
            kwargs.update(context)

        return template.format(**kwargs)



class Response(Entry, kw_only=True):
    level: LogLevel = LogLevel.INFO
    path: str | None = None
    protocol: Literal['HTTP/1.1']='HTTP/1.1'
    method: str | None = None
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
        ] = {field: getattr(self, field) for field in self.__struct_fields__ if getattr(self, field) is not None}

        kwargs["level"] = kwargs["level"].value

        if context:
            kwargs.update(context)

        return template.format(**kwargs)

