from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mkfst.middleware.base.response_context import ResponseContext
from mkfst.middleware.csrf import CSRF, CSRFConfigurationError


def _ctx(
    method: str = "POST",
    path: str = "/api/x",
    cookie: str | None = None,
    header_value: str | None = None,
    header_name: str = "x-csrftoken",
) -> ResponseContext:
    headers: dict[str, Any] = {}
    if cookie is not None:
        headers["cookie"] = f"csrftoken={cookie}"
    if header_value is not None:
        headers[header_name] = header_value

    ctx = ResponseContext(
        path=path,
        method=method,
        headers=headers,
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
    return ctx


class _FabricatorStub:
    """Minimal stub matching `Fabricator.param_keys` for the cookies/headers
    extraction path inside ResponseContext.get_headers_and_cookies."""

    param_keys: dict[str, Any] = {}


def _attach_stub(ctx: ResponseContext) -> None:
    ctx.fabricator = _FabricatorStub()


async def _run(middleware: CSRF, ctx: ResponseContext, response: Any = None):
    _attach_stub(ctx)
    return await middleware.__run__(context=ctx, response=response, handler=None)


def test_rejects_too_small_nonce() -> None:
    with pytest.raises(CSRFConfigurationError, match="nonce_bytes"):
        CSRF(nonce_bytes=4)


def test_samesite_none_requires_secure() -> None:
    with pytest.raises(CSRFConfigurationError, match="samesite='none'"):
        CSRF(cookie_samesite="none", cookie_secure=False)


async def test_safe_method_with_no_token_issues_one() -> None:
    middleware = CSRF(required_paths=["/api"])
    ctx = _ctx(method="GET")
    (returned, _), cont = await _run(middleware, ctx)
    assert cont is True
    set_cookie = returned.response_headers["set-cookie"]
    assert set_cookie.startswith("csrftoken=")
    assert "Secure" in set_cookie
    assert "SameSite=Lax" in set_cookie
    assert "HttpOnly" not in set_cookie
    assert returned.response_headers["x-csrftoken"]


async def test_unsafe_method_without_token_rejected() -> None:
    middleware = CSRF(required_paths=["/api"])
    ctx = _ctx(method="POST", path="/api/x")
    (returned, body), cont = await _run(middleware, ctx)
    assert cont is False
    assert returned.status == 403
    assert "missing" in body


async def test_valid_double_submit_passes() -> None:
    middleware = CSRF(required_paths=["/api"])
    issue_ctx = _ctx(method="GET")
    await _run(middleware, issue_ctx)
    token = issue_ctx.response_headers["x-csrftoken"]

    ctx = _ctx(method="POST", path="/api/x", cookie=token, header_value=token)
    (returned, _), cont = await _run(middleware, ctx)
    assert cont is True
    assert returned.status is None


async def test_mismatched_double_submit_rejected() -> None:
    middleware = CSRF(required_paths=["/api"])
    issue_ctx_a = _ctx(method="GET")
    await _run(middleware, issue_ctx_a)
    token_a = issue_ctx_a.response_headers["x-csrftoken"]

    issue_ctx_b = _ctx(method="GET")
    await _run(middleware, issue_ctx_b)
    token_b = issue_ctx_b.response_headers["x-csrftoken"]

    ctx = _ctx(method="POST", path="/api/x", cookie=token_a, header_value=token_b)
    (returned, body), cont = await _run(middleware, ctx)
    assert cont is False
    assert returned.status == 403
    assert "mismatch" in body


async def test_tampered_token_rejected() -> None:
    middleware = CSRF(required_paths=["/api"])
    issue = _ctx(method="GET")
    await _run(middleware, issue)
    token = issue.response_headers["x-csrftoken"]
    tampered = token[:-2] + ("AA" if token[-2:] != "AA" else "BB")

    ctx = _ctx(method="POST", path="/api/x", cookie=tampered, header_value=tampered)
    (_, body), cont = await _run(middleware, ctx)
    assert cont is False
    assert "authentication failed" in body or "malformed" in body


async def test_token_from_other_cookie_name_rejected() -> None:
    """AAD-binding: a token issued under cookie_name='csrftoken' must NOT
    decrypt under cookie_name='other'."""
    a = CSRF(required_paths=["/api"], cookie_name="csrftoken")
    b = CSRF(required_paths=["/api"], cookie_name="other")
    issue = _ctx(method="GET")
    await _run(a, issue)
    token_for_a = issue.response_headers["x-csrftoken"]

    ctx = _ctx(method="POST", path="/api/x", cookie=token_for_a, header_value=token_for_a)
    # The cookie header shape is "csrftoken=..." but b.cookie_name='other', so
    # b will see no cookie. Re-stage with the right cookie name to isolate the
    # AAD test:
    ctx.request_headers["cookie"] = f"other={token_for_a}"
    (_, body), cont = await _run(b, ctx)
    assert cont is False
    assert "authentication failed" in body


async def test_expired_token_rejected() -> None:
    middleware = CSRF(required_paths=["/api"], max_age_seconds=1)
    issue = _ctx(method="GET")
    await _run(middleware, issue)
    token = issue.response_headers["x-csrftoken"]
    await asyncio.sleep(1.05)
    ctx = _ctx(method="POST", path="/api/x", cookie=token, header_value=token)
    (_, body), cont = await _run(middleware, ctx)
    assert cont is False
    assert "expired" in body


async def test_exempt_path_skips_validation() -> None:
    middleware = CSRF(required_paths=["/api"], exempt_paths=["/api/webhook"])
    ctx = _ctx(method="POST", path="/api/webhook")
    (returned, _), cont = await _run(middleware, ctx)
    assert cont is True


async def test_safe_method_does_not_validate() -> None:
    middleware = CSRF(required_paths=["/api"])
    ctx = _ctx(method="GET", path="/api/x")
    (returned, _), cont = await _run(middleware, ctx)
    assert cont is True


async def test_path_not_in_required_skipped() -> None:
    middleware = CSRF(required_paths=["/api"])
    ctx = _ctx(method="POST", path="/public")
    (returned, _), cont = await _run(middleware, ctx)
    assert cont is True


async def test_sensitive_cookies_force_validation_when_unsafe() -> None:
    middleware = CSRF(sensitive_cookies={"session_id"})
    # Has session cookie + unsafe method but no csrf token → reject.
    ctx = _ctx(method="POST", path="/anything")
    ctx.request_headers["cookie"] = "session_id=abc"
    (returned, _), cont = await _run(middleware, ctx)
    assert cont is False
    assert returned.status == 403
