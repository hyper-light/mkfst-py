"""Internal helpers for CORS header emission. The on-the-wire formatting is
deliberately literal: comma-joined methods/headers, integer max-age, no
``*`` ACAO when credentials are involved.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

SAFE_REQUEST_HEADERS = frozenset(
    {"accept", "accept-language", "content-language", "content-type"}
)


def render_methods(
    methods: Iterable[
        Literal["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE", "TRACE"]
    ],
) -> str:
    return ", ".join(methods)


def render_headers(headers: Iterable[str]) -> str:
    return ", ".join(headers)


def render_max_age(max_age: int | float | None) -> str | None:
    if max_age is None:
        return None
    return str(int(max_age))
