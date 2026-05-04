from __future__ import annotations

from typing import Any

import pytest

from mkfst.middleware.base.response_context import ResponseContext
from mkfst.middleware.cors import Cors, CorsConfigurationError


def _ctx(
    method: str = "GET",
    headers: dict[str, Any] | None = None,
) -> ResponseContext:
    return ResponseContext(
        path="/",
        method=method,
        headers=headers or {},
        params={},
        query="",
        data=[],
        args=(),
        kwargs={},
        fabricator=None,  # type: ignore[arg-type]
        parser=None,  # type: ignore[arg-type]
        ip_address="127.0.0.1",
        protocol="https",
        request_addr=("127.0.0.1", 0),
        upgrade_port=0,
    )


async def _run(cors: Cors, ctx: ResponseContext, response: Any = None):
    return await cors.__run__(context=ctx, response=response, handler=None)


def test_constructor_rejects_wildcard_with_credentials() -> None:
    with pytest.raises(CorsConfigurationError, match="wildcard"):
        Cors(
            access_control_allow_origin=["*"],
            access_control_allow_methods=["GET"],
            access_control_allow_credentials=True,
        )


def test_constructor_requires_origin_list() -> None:
    with pytest.raises(CorsConfigurationError, match="origin"):
        Cors(access_control_allow_origin=[], access_control_allow_methods=["GET"])


def test_constructor_requires_methods() -> None:
    with pytest.raises(CorsConfigurationError, match="methods"):
        Cors(access_control_allow_origin=["https://a"], access_control_allow_methods=[])


async def test_simple_request_with_allowed_origin_gets_acao() -> None:
    cors = Cors(
        access_control_allow_origin=["https://app.example"],
        access_control_allow_methods=["GET"],
    )
    ctx = _ctx(headers={"origin": "https://app.example"})
    (returned, _), cont = await _run(cors, ctx)
    assert cont is True
    assert returned.response_headers["Access-Control-Allow-Origin"] == "https://app.example"
    assert returned.response_headers["Vary"] == "Origin"


async def test_simple_request_with_disallowed_origin_omits_acao() -> None:
    cors = Cors(
        access_control_allow_origin=["https://app.example"],
        access_control_allow_methods=["GET"],
    )
    ctx = _ctx(headers={"origin": "https://evil.example"})
    (returned, _), cont = await _run(cors, ctx)
    assert cont is True
    assert "Access-Control-Allow-Origin" not in returned.response_headers


async def test_wildcard_origin_emits_star_when_no_credentials() -> None:
    cors = Cors(
        access_control_allow_origin=["*"],
        access_control_allow_methods=["GET"],
    )
    ctx = _ctx(headers={"origin": "https://anywhere.example"})
    (returned, _), cont = await _run(cors, ctx)
    assert cont is True
    assert returned.response_headers["Access-Control-Allow-Origin"] == "*"


async def test_credentialed_request_uses_specific_origin() -> None:
    cors = Cors(
        access_control_allow_origin=["https://app.example"],
        access_control_allow_methods=["GET"],
        access_control_allow_credentials=True,
    )
    ctx = _ctx(headers={"origin": "https://app.example"})
    (returned, _), _ = await _run(cors, ctx)
    assert returned.response_headers["Access-Control-Allow-Origin"] == "https://app.example"
    assert returned.response_headers["Access-Control-Allow-Credentials"] == "true"


async def test_preflight_success_emits_max_age_as_integer() -> None:
    cors = Cors(
        access_control_allow_origin=["https://app.example"],
        access_control_allow_methods=["GET", "POST"],
        access_control_max_age=600,
    )
    ctx = _ctx(
        method="OPTIONS",
        headers={
            "origin": "https://app.example",
            "access-control-request-method": "POST",
        },
    )
    (returned, _), cont = await _run(cors, ctx)
    assert cont is False  # Preflight short-circuits the chain.
    assert returned.status == 204
    assert returned.response_headers["Access-Control-Max-Age"] == "600"
    assert returned.response_headers["Access-Control-Allow-Methods"] == "GET, POST"


async def test_preflight_failure_omits_allow_headers() -> None:
    cors = Cors(
        access_control_allow_origin=["https://app.example"],
        access_control_allow_methods=["GET"],
    )
    ctx = _ctx(
        method="OPTIONS",
        headers={
            "origin": "https://evil.example",
            "access-control-request-method": "GET",
        },
    )
    (returned, _), cont = await _run(cors, ctx)
    assert cont is False
    assert returned.status == 204
    assert "Access-Control-Allow-Origin" not in returned.response_headers
    assert "Access-Control-Allow-Methods" not in returned.response_headers


async def test_preflight_with_disallowed_method_rejected() -> None:
    cors = Cors(
        access_control_allow_origin=["https://app.example"],
        access_control_allow_methods=["GET"],
    )
    ctx = _ctx(
        method="OPTIONS",
        headers={
            "origin": "https://app.example",
            "access-control-request-method": "DELETE",
        },
    )
    (returned, _), cont = await _run(cors, ctx)
    assert cont is False
    assert "Access-Control-Allow-Methods" not in returned.response_headers


async def test_preflight_disallowed_request_headers_rejected() -> None:
    cors = Cors(
        access_control_allow_origin=["https://app.example"],
        access_control_allow_methods=["POST"],
        access_control_allow_headers=["X-App-Auth"],
    )
    ctx = _ctx(
        method="OPTIONS",
        headers={
            "origin": "https://app.example",
            "access-control-request-method": "POST",
            "access-control-request-headers": "X-Forbidden",
        },
    )
    (returned, _), cont = await _run(cors, ctx)
    assert cont is False
    assert "Access-Control-Allow-Headers" not in returned.response_headers


async def test_safelisted_request_headers_always_allowed_in_preflight() -> None:
    cors = Cors(
        access_control_allow_origin=["https://app.example"],
        access_control_allow_methods=["POST"],
    )
    ctx = _ctx(
        method="OPTIONS",
        headers={
            "origin": "https://app.example",
            "access-control-request-method": "POST",
            "access-control-request-headers": "Content-Type, Accept",
        },
    )
    (returned, _), cont = await _run(cors, ctx)
    assert cont is False
    assert returned.status == 204
    assert "Access-Control-Allow-Origin" in returned.response_headers


async def test_no_origin_passes_through_with_vary() -> None:
    cors = Cors(
        access_control_allow_origin=["https://app.example"],
        access_control_allow_methods=["GET"],
    )
    ctx = _ctx()
    (returned, _), cont = await _run(cors, ctx)
    assert cont is True
    assert returned.response_headers.get("Vary") == "Origin"
    assert "Access-Control-Allow-Origin" not in returned.response_headers


async def test_expose_headers_emitted_on_actual() -> None:
    cors = Cors(
        access_control_allow_origin=["https://app.example"],
        access_control_allow_methods=["GET"],
        access_control_expose_headers=["X-RateLimit-Remaining", "X-Request-Id"],
    )
    ctx = _ctx(headers={"origin": "https://app.example"})
    (returned, _), _ = await _run(cors, ctx)
    assert (
        returned.response_headers["Access-Control-Expose-Headers"]
        == "X-RateLimit-Remaining, X-Request-Id"
    )
