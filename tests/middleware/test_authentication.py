from __future__ import annotations

from typing import Any

import pytest

from mkfst.middleware.auth import Authentication
from mkfst.middleware.base.response_context import ResponseContext


def _ctx(method: str = "GET", path: str = "/x") -> ResponseContext:
    return ResponseContext(
        path=path,
        method=method,
        headers={},
        params={},
        query="",
        data=[],
        args=(),
        kwargs={},
        fabricator=None,  # type: ignore[arg-type]
        parser=None,  # type: ignore[arg-type]
        ip_address="127.0.0.1",
        protocol="http",
        request_addr=("127.0.0.1", 0),
        upgrade_port=0,
    )


def test_rejects_non_callable_authenticator() -> None:
    with pytest.raises(TypeError, match="callable"):
        Authentication("not-callable")  # type: ignore[arg-type]


async def test_sync_authenticator_true_passes() -> None:
    middleware = Authentication(lambda ctx: True)
    ctx = _ctx()
    (returned_ctx, response), continue_chain = await middleware.__run__(
        context=ctx, response=None, handler=None
    )
    assert continue_chain is True
    assert returned_ctx is ctx
    assert returned_ctx.status is None
    assert returned_ctx.principal is None


async def test_sync_authenticator_false_returns_401() -> None:
    middleware = Authentication(lambda ctx: False)
    ctx = _ctx()
    (returned_ctx, body), continue_chain = await middleware.__run__(
        context=ctx, response=None, handler=None
    )
    assert continue_chain is False
    assert returned_ctx.status == 401
    assert body == "Unauthorized"


async def test_sync_authenticator_none_returns_401() -> None:
    middleware = Authentication(lambda ctx: None)
    ctx = _ctx()
    (_, _), cont = await middleware.__run__(context=ctx, response=None, handler=None)
    assert cont is False
    assert ctx.status == 401


async def test_principal_attached_on_truthy_payload() -> None:
    sentinel = {"user_id": 42}
    middleware = Authentication(lambda ctx: (True, sentinel))
    ctx = _ctx()
    (returned_ctx, _), cont = await middleware.__run__(context=ctx, response=None, handler=None)
    assert cont is True
    assert returned_ctx.principal is sentinel


async def test_non_tuple_truthy_treated_as_principal() -> None:
    middleware = Authentication(lambda ctx: "alice")
    ctx = _ctx()
    (returned_ctx, _), cont = await middleware.__run__(context=ctx, response=None, handler=None)
    assert cont is True
    assert returned_ctx.principal == "alice"


async def test_failure_with_reason_string_returned_as_body() -> None:
    middleware = Authentication(lambda ctx: (False, "bad token"))
    ctx = _ctx()
    (returned_ctx, body), cont = await middleware.__run__(context=ctx, response=None, handler=None)
    assert cont is False
    assert returned_ctx.status == 401
    assert body == "bad token"


async def test_async_authenticator_supported() -> None:
    async def auth(ctx: ResponseContext) -> bool:
        return ctx.method == "GET"

    middleware = Authentication(auth)
    ok_ctx = _ctx("GET")
    (_, _), cont_ok = await middleware.__run__(context=ok_ctx, response=None, handler=None)
    assert cont_ok is True

    fail_ctx = _ctx("POST")
    (_, _), cont_fail = await middleware.__run__(context=fail_ctx, response=None, handler=None)
    assert cont_fail is False
    assert fail_ctx.status == 401


async def test_class_with_async_call_supported() -> None:
    class AsyncAuth:
        async def __call__(self, ctx: ResponseContext) -> Any:
            return True

    middleware = Authentication(AsyncAuth())
    ctx = _ctx()
    (_, _), cont = await middleware.__run__(context=ctx, response=None, handler=None)
    assert cont is True


async def test_authenticator_exception_returns_500() -> None:
    def boom(ctx: ResponseContext) -> bool:
        raise RuntimeError("oops")

    middleware = Authentication(boom)
    ctx = _ctx()
    (returned_ctx, _), cont = await middleware.__run__(context=ctx, response=None, handler=None)
    assert cont is False
    assert returned_ctx.status == 500
    assert returned_ctx.errors and isinstance(returned_ctx.errors[0], RuntimeError)


async def test_www_authenticate_header_emitted_on_failure() -> None:
    middleware = Authentication(
        lambda ctx: False,
        www_authenticate='Bearer realm="api"',
    )
    ctx = _ctx()
    (returned_ctx, _), _ = await middleware.__run__(context=ctx, response=None, handler=None)
    assert returned_ctx.response_headers["www-authenticate"] == 'Bearer realm="api"'


async def test_failure_status_overridable() -> None:
    middleware = Authentication(lambda ctx: False, failure_status=403)
    ctx = _ctx()
    (returned_ctx, _), _ = await middleware.__run__(context=ctx, response=None, handler=None)
    assert returned_ctx.status == 403
