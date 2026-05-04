from __future__ import annotations

import pytest

from mkfst.connection.tcp.protocols.http_parser import (
    ParseError,
    classify_body_framing,
    parse_request_head,
    read_body,
)
from mkfst.connection.tcp.protocols.receive_buffer import ReceiveBuffer

HEAD_MAX = 64 * 1024
BODY_MAX = 1 * 1024 * 1024
CHUNK_MAX = 256 * 1024


def _head(raw: bytes):
    return parse_request_head(raw, max_header_bytes=HEAD_MAX)


def test_basic_get_parses() -> None:
    head = _head(b"GET /foo HTTP/1.1\r\nHost: example\r\n\r\n")
    assert head.method == "GET"
    assert head.path == "/foo"
    assert head.query == ""
    assert head.http_version == (1, 1)
    assert head.headers["host"] == "example"


def test_query_string_split() -> None:
    head = _head(b"GET /foo?a=1&b=2 HTTP/1.1\r\nHost: x\r\n\r\n")
    assert head.path == "/foo"
    assert head.query == "a=1&b=2"


def test_header_names_lowercased() -> None:
    head = _head(b"GET / HTTP/1.1\r\nHOST: x\r\nContent-Type: a\r\n\r\n")
    assert "host" in head.headers
    assert "content-type" in head.headers


def test_obsolete_line_fold_rejected() -> None:
    raw = b"GET / HTTP/1.1\r\nHost: x\r\nX-Folded: a\r\n  continuation\r\n\r\n"
    with pytest.raises(ParseError, match="obsolete line folding"):
        _head(raw)


def test_duplicate_host_rejected() -> None:
    raw = b"GET / HTTP/1.1\r\nHost: a\r\nHost: b\r\n\r\n"
    with pytest.raises(ParseError, match="duplicate host"):
        _head(raw)


def test_duplicate_cl_rejected() -> None:
    raw = b"POST / HTTP/1.1\r\nHost: x\r\nContent-Length: 5\r\nContent-Length: 5\r\n\r\n"
    with pytest.raises(ParseError, match="duplicate content-length"):
        _head(raw)


def test_duplicate_te_rejected() -> None:
    raw = (
        b"POST / HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n"
        b"Transfer-Encoding: chunked\r\n\r\n"
    )
    with pytest.raises(ParseError, match="duplicate transfer-encoding"):
        _head(raw)


def test_oversized_head_rejected() -> None:
    big = b"GET / HTTP/1.1\r\nHost: x\r\nX-Big: " + (b"a" * 200) + b"\r\n\r\n"
    with pytest.raises(ParseError, match="too large"):
        parse_request_head(big, max_header_bytes=64)


def test_invalid_request_line() -> None:
    with pytest.raises(ParseError, match="invalid request line"):
        _head(b"NOT A REAL REQUEST\r\n\r\n")


def test_unsupported_http_version() -> None:
    with pytest.raises(ParseError, match="unsupported HTTP version"):
        _head(b"GET / HTTP/2.0\r\nHost: x\r\n\r\n")


def test_null_byte_rejected() -> None:
    with pytest.raises(ParseError, match="null byte"):
        _head(b"GET / HTTP/1.1\r\nHost: x\x00y\r\n\r\n")


def test_classify_post_with_cl() -> None:
    kind, length = classify_body_framing("POST", {"host": "x", "content-length": "5"})
    assert kind == "fixed"
    assert length == 5


def test_classify_post_with_chunked() -> None:
    kind, length = classify_body_framing("POST", {"host": "x", "transfer-encoding": "chunked"})
    assert kind == "chunked"
    assert length is None


def test_classify_cl_and_te_rejected() -> None:
    with pytest.raises(ParseError, match="cannot both be present"):
        classify_body_framing("POST", {"content-length": "5", "transfer-encoding": "chunked"})


def test_classify_unknown_te_rejected() -> None:
    with pytest.raises(ParseError, match="unsupported Transfer-Encoding"):
        classify_body_framing("POST", {"transfer-encoding": "gzip"})


def test_classify_negative_cl_rejected() -> None:
    with pytest.raises(ParseError, match="invalid Content-Length"):
        classify_body_framing("POST", {"content-length": "-1"})


def test_classify_signed_cl_rejected() -> None:
    with pytest.raises(ParseError, match="invalid Content-Length"):
        classify_body_framing("POST", {"content-length": "+10"})


def test_classify_post_without_framing_411() -> None:
    with pytest.raises(ParseError) as excinfo:
        classify_body_framing("POST", {"host": "x"})
    assert excinfo.value.status_code == 411


def test_classify_get_without_framing_ok() -> None:
    kind, length = classify_body_framing("GET", {"host": "x"})
    assert kind == "none"
    assert length == 0


async def _read_now(buffer: ReceiveBuffer, length: int) -> bytes:
    return await read_body(
        "fixed",
        length,
        buffer,
        max_body_bytes=BODY_MAX,
        max_chunk_bytes=CHUNK_MAX,
        read_more=_immediate_eof,
    )


async def _immediate_eof():
    raise ParseError("buffer exhausted before body complete")


async def test_fixed_body_exact() -> None:
    buf = ReceiveBuffer()
    buf += b"hello world"
    body = await _read_now(buf, 11)
    assert body == b"hello world"
    assert len(buf) == 0


async def test_fixed_body_off_by_one_does_not_consume_extra() -> None:
    """The pre-fix parser did `extract_at_most(content_length + 1)` and ate
    a byte from the next pipelined request."""
    buf = ReceiveBuffer()
    buf += b"PINGNEXT"
    body = await _read_now(buf, 4)
    assert body == b"PING"
    # Whatever remains in the buffer must be the next pipelined request as
    # exposed by the public API.
    assert bytes(buf) == b"NEXT"


async def test_fixed_body_too_large() -> None:
    with pytest.raises(ParseError) as excinfo:
        await read_body(
            "fixed",
            BODY_MAX + 1,
            ReceiveBuffer(),
            max_body_bytes=BODY_MAX,
            max_chunk_bytes=CHUNK_MAX,
            read_more=_immediate_eof,
        )
    assert excinfo.value.status_code == 413


async def test_chunked_body_simple() -> None:
    buf = ReceiveBuffer()
    buf += b"5\r\nhello\r\n6\r\n world\r\n0\r\n\r\n"
    body = await read_body(
        "chunked",
        None,
        buf,
        max_body_bytes=BODY_MAX,
        max_chunk_bytes=CHUNK_MAX,
        read_more=_immediate_eof,
    )
    assert body == b"hello world"


async def test_chunked_body_with_extensions_ignored() -> None:
    buf = ReceiveBuffer()
    buf += b"5;name=value\r\nhello\r\n0\r\n\r\n"
    body = await read_body(
        "chunked",
        None,
        buf,
        max_body_bytes=BODY_MAX,
        max_chunk_bytes=CHUNK_MAX,
        read_more=_immediate_eof,
    )
    assert body == b"hello"


async def test_chunked_body_with_trailers_consumed() -> None:
    buf = ReceiveBuffer()
    buf += b"5\r\nhello\r\n0\r\nTrailer-A: foo\r\n\r\n"
    body = await read_body(
        "chunked",
        None,
        buf,
        max_body_bytes=BODY_MAX,
        max_chunk_bytes=CHUNK_MAX,
        read_more=_immediate_eof,
    )
    assert body == b"hello"
    assert len(buf) == 0


async def test_chunked_per_chunk_limit() -> None:
    buf = ReceiveBuffer()
    huge_size_hex = format(CHUNK_MAX + 1, "x").encode()
    buf += huge_size_hex + b"\r\n"
    with pytest.raises(ParseError) as excinfo:
        await read_body(
            "chunked",
            None,
            buf,
            max_body_bytes=BODY_MAX,
            max_chunk_bytes=CHUNK_MAX,
            read_more=_immediate_eof,
        )
    assert excinfo.value.status_code == 413


async def test_chunked_body_total_limit() -> None:
    buf = ReceiveBuffer()
    half = CHUNK_MAX // 2
    body = b"a" * half
    buf += format(half, "x").encode() + b"\r\n" + body + b"\r\n"
    buf += format(half, "x").encode() + b"\r\n" + body + b"\r\n"
    buf += format(half, "x").encode() + b"\r\n" + body + b"\r\n"
    with pytest.raises(ParseError) as excinfo:
        await read_body(
            "chunked",
            None,
            buf,
            max_body_bytes=half * 2,  # smaller total cap
            max_chunk_bytes=CHUNK_MAX,
            read_more=_immediate_eof,
        )
    assert excinfo.value.status_code == 413


async def test_chunked_invalid_size_rejected() -> None:
    buf = ReceiveBuffer()
    buf += b"ZZ\r\nhello\r\n0\r\n\r\n"
    with pytest.raises(ParseError, match="invalid chunk size"):
        await read_body(
            "chunked",
            None,
            buf,
            max_body_bytes=BODY_MAX,
            max_chunk_bytes=CHUNK_MAX,
            read_more=_immediate_eof,
        )


async def test_chunked_missing_crlf_after_data_rejected() -> None:
    buf = ReceiveBuffer()
    buf += b"5\r\nhelloXX0\r\n\r\n"
    with pytest.raises(ParseError, match="missing CRLF"):
        await read_body(
            "chunked",
            None,
            buf,
            max_body_bytes=BODY_MAX,
            max_chunk_bytes=CHUNK_MAX,
            read_more=_immediate_eof,
        )


async def test_chunked_streamed_across_reads() -> None:
    """Body arrives in multiple read_more invocations."""
    buf = ReceiveBuffer()

    pieces = [b"5\r\nhel", b"lo\r\n", b"6\r\n wor", b"ld\r\n", b"0\r\n\r\n"]
    it = iter(pieces)

    async def feed():
        try:
            buf.__iadd__(next(it))
        except StopIteration:
            raise ParseError("eof")

    body = await read_body(
        "chunked",
        None,
        buf,
        max_body_bytes=BODY_MAX,
        max_chunk_bytes=CHUNK_MAX,
        read_more=feed,
    )
    assert body == b"hello world"
