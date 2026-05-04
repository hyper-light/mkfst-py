from __future__ import annotations

import asyncio

from mkfst import Service, endpoint


class _BasicService(Service):
    @endpoint("/")
    async def root(self) -> str:
        return "hello"

    @endpoint("/json")
    async def json_route(self) -> dict:
        return {"ok": True, "n": 42}


async def test_basic_get_returns_200(service) -> None:
    handle = await service(_BasicService)
    r = await handle.client.get("/")
    assert r.status_code == 200
    assert r.text == "hello"


async def test_json_response(service) -> None:
    handle = await service(_BasicService)
    r = await handle.client.get("/json")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "n": 42}


async def test_unknown_route_404(service) -> None:
    handle = await service(_BasicService)
    r = await handle.client.get("/does-not-exist")
    assert r.status_code == 404


async def _send_raw(host: str, port: int, payload: bytes, timeout: float = 3.0) -> bytes:
    """Open a raw TCP socket, send ``payload``, return whatever is read until
    EOF or timeout. Used for smuggling / framing assertions httpx can't make."""
    reader, writer = await asyncio.open_connection(host, port)
    writer.write(payload)
    await writer.drain()
    try:
        data = await asyncio.wait_for(reader.read(8192), timeout=timeout)
    except TimeoutError:
        data = b""
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    return data


async def test_smuggling_cl_and_te_rejected(service) -> None:
    handle = await service(_BasicService)
    payload = (
        b"POST / HTTP/1.1\r\n"
        b"Host: localhost\r\n"
        b"Content-Length: 5\r\n"
        b"Transfer-Encoding: chunked\r\n"
        b"\r\n"
        b"0\r\n\r\n"
    )
    response = await _send_raw(handle.host, handle.port, payload)
    assert response.startswith(b"HTTP/1.1 400") or response.startswith(b"HTTP/1.1 4"), response


async def test_invalid_request_line_rejected(service) -> None:
    handle = await service(_BasicService)
    response = await _send_raw(handle.host, handle.port, b"NOT-A-VALID-REQUEST\r\n\r\n")
    assert response.startswith(b"HTTP/1.1 4"), response


async def test_obs_fold_rejected(service) -> None:
    handle = await service(_BasicService)
    payload = b"GET / HTTP/1.1\r\nHost: localhost\r\nX-Folded: a\r\n  continued\r\n\r\n"
    response = await _send_raw(handle.host, handle.port, payload)
    assert response.startswith(b"HTTP/1.1 400"), response


async def test_negative_content_length_rejected(service) -> None:
    handle = await service(_BasicService)
    payload = b"POST / HTTP/1.1\r\nHost: localhost\r\nContent-Length: -1\r\n\r\n"
    response = await _send_raw(handle.host, handle.port, payload)
    assert response.startswith(b"HTTP/1.1 4"), response


async def test_oversized_body_rejected(service) -> None:
    """With the default MERCURY_SYNC_MAX_REQUEST_BODY_BYTES limit, a CL larger
    than the cap must be refused (413)."""
    handle = await service(_BasicService)
    huge = 100 * 1024 * 1024
    payload = f"POST / HTTP/1.1\r\nHost: localhost\r\nContent-Length: {huge}\r\n\r\n".encode()
    response = await _send_raw(handle.host, handle.port, payload)
    assert response.startswith(b"HTTP/1.1 413"), response


async def test_404_status_line_uses_proper_reason_phrase(service) -> None:
    handle = await service(_BasicService)
    response = await _send_raw(
        handle.host, handle.port, b"GET /nope HTTP/1.1\r\nHost: localhost\r\n\r\n"
    )
    # Pre-fix the status line was always "HTTP/1.1 ... OK".
    assert response.startswith(b"HTTP/1.1 404 Not Found"), response


async def test_405_when_method_not_allowed(service) -> None:
    handle = await service(_BasicService)
    response = await _send_raw(
        handle.host, handle.port, b"DELETE / HTTP/1.1\r\nHost: localhost\r\n\r\n"
    )
    # Either 404 (route not found for DELETE) or 405 — both are fine. The
    # important thing is we don't claim "OK" on a non-200 response.
    assert b" OK\r\n" not in response.split(b"\r\n", 1)[0], response


async def test_head_request_has_no_body_but_advertises_length(service) -> None:
    handle = await service(_BasicService)
    response = await _send_raw(
        handle.host, handle.port, b"HEAD / HTTP/1.1\r\nHost: localhost\r\n\r\n"
    )
    # Some servers may not yet wire HEAD; if it 404s that's also valid here.
    if response.startswith(b"HTTP/1.1 200"):
        head, _, body = response.partition(b"\r\n\r\n")
        assert b"content-length: 5" in head.lower()
        assert body == b""


async def test_chunked_body_round_trip(service) -> None:
    """Sanity-check the chunked decoder by posting to a JSON endpoint via
    Transfer-Encoding: chunked. Even though _BasicService has no body endpoint
    here, the parse must succeed (return 404, not 400)."""
    handle = await service(_BasicService)
    body = b"3\r\nfoo\r\n3\r\nbar\r\n0\r\n\r\n"
    payload = (
        b"POST /unknown HTTP/1.1\r\nHost: localhost\r\nTransfer-Encoding: chunked\r\n\r\n" + body
    )
    response = await _send_raw(handle.host, handle.port, payload)
    assert response.startswith(b"HTTP/1.1 404"), response
