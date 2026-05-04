"""RFC 7230-compliant HTTP/1.1 request head + body parsing.

Designed for raw-asyncio mkfst on top of ``ReceiveBuffer``. The parser is
deliberately strict (rejects request smuggling vectors at the door) and
allocation-aware (single decode of the head, lowercase header names interned
into a plain ``dict``).

Threats handled here:

* Content-Length + Transfer-Encoding both present → reject (CL/TE smuggling).
* Multiple, conflicting Content-Length values → reject.
* Negative or sign-prefixed Content-Length → reject.
* Body or header sections larger than the configured maxima → reject.
* Obsolete header line folding (RFC 7230 §3.2.4) → reject.
* Chunk size exceeding the per-chunk maximum → reject.
* Chunk extensions are tolerated and ignored per RFC.
* Malformed chunk terminators → reject.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .receive_buffer import ReceiveBuffer

_REQUEST_LINE_RE = re.compile(rb"^([A-Z]+) ([!-~]+) HTTP/(\d)\.(\d)$")
_HEADER_RE = re.compile(rb"^([!-9;-~]+):[ \t]*(.*?)[ \t]*$")
_OWS_LEADING = (0x20, 0x09)  # SP, HT
_TOKEN_DIGITS = re.compile(rb"^[0-9]+$")

# Pre-intern method and common header names so parsed strings share storage
# with the canonical objects: smaller working set, cached hashes on dict
# inserts, and identity-equality short-circuit on consumer lookups against
# matching string literals. Unknown header names are left non-interned —
# the intern table must not be polluted by peer-controlled input.
_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
_INTERNED_METHODS: dict[str, str] = {sys.intern(m): sys.intern(m) for m in _METHODS}

_COMMON_HEADER_NAMES = (
    "host",
    "content-length",
    "content-type",
    "content-encoding",
    "transfer-encoding",
    "connection",
    "expect",
    "upgrade",
    "user-agent",
    "accept",
    "accept-encoding",
    "accept-language",
    "authorization",
    "cookie",
    "set-cookie",
    "origin",
    "referer",
    "cache-control",
    "if-none-match",
    "if-modified-since",
    "etag",
    "x-forwarded-for",
    "x-forwarded-proto",
    "x-real-ip",
    "x-requested-with",
    "x-csrf-token",
    "x-compression-encoding",
    "date",
    "server",
    "location",
    "vary",
    "pragma",
    "access-control-allow-origin",
    "access-control-allow-headers",
    "access-control-allow-methods",
    "access-control-allow-credentials",
    "access-control-request-method",
    "access-control-request-headers",
)
_INTERNED_HEADERS: dict[str, str] = {sys.intern(n): sys.intern(n) for n in _COMMON_HEADER_NAMES}

# Module constants for header names the parser inspects directly. Reusing
# these (vs literal "host" each call) means each request reuses the same
# interned object the dict was keyed with.
HOST = sys.intern("host")
CONTENT_LENGTH = sys.intern("content-length")
TRANSFER_ENCODING = sys.intern("transfer-encoding")
_DUPLICATE_REJECT = frozenset((HOST, CONTENT_LENGTH, TRANSFER_ENCODING))


class ParseError(Exception):
    """Raised when the request head/body is malformed or violates configured limits.

    The carried message is intentionally generic so it can safely be returned
    in 4xx response bodies without leaking parser internals to peers.
    """

    __slots__ = ("status_code",)

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(slots=True)
class RequestHead:
    method: str
    path: str
    query: str
    http_version: tuple[int, int]
    headers: dict[str, str]
    raw_size: int


def parse_request_head(
    raw: bytes | bytearray | memoryview,
    max_header_bytes: int,
) -> RequestHead:
    """Parse the request line and headers from a single byte block already
    extracted up to (and including) the terminating blank line."""
    if len(raw) > max_header_bytes:
        raise ParseError("request header section too large", status_code=431)

    # Normalize line endings: HTTP requires CRLF; tolerate bare LF for the
    # internal split but reject any line that contains a stray CR mid-line
    # (those are smuggling indicators).
    if b"\x00" in raw:
        raise ParseError("null byte in request head")

    lines = raw.split(b"\n")
    # The trailing blank line yields one or two empty trailing entries; drop them.
    while lines and lines[-1] in (b"", b"\r"):
        lines.pop()
    if not lines:
        raise ParseError("empty request head")

    cleaned: list[bytes] = []
    for line in lines:
        if line.endswith(b"\r"):
            line = line[:-1]
        if b"\r" in line:
            raise ParseError("embedded CR in header line")
        cleaned.append(line)

    request_line = cleaned[0]
    match = _REQUEST_LINE_RE.match(request_line)
    if match is None:
        raise ParseError("invalid request line")

    method_raw = match.group(1).decode("ascii")
    method = _INTERNED_METHODS.get(method_raw, method_raw)
    target = match.group(2).decode("ascii")
    major = int(match.group(3))
    minor = int(match.group(4))

    if major != 1 or minor not in (0, 1):
        raise ParseError("unsupported HTTP version", status_code=505)

    if "?" in target:
        path, _, query = target.partition("?")
    else:
        path, query = target, ""

    headers: dict[str, str] = {}
    for line in cleaned[1:]:
        if not line:
            continue
        # RFC 7230 §3.2.4: SHOULD reject obs-fold (a header line beginning
        # with whitespace continuing the previous one). We hard-reject — it's
        # a known request-smuggling lever.
        if line[0] in _OWS_LEADING:
            raise ParseError("obsolete line folding rejected")

        m = _HEADER_RE.match(line)
        if m is None:
            raise ParseError("malformed header line")

        name_raw = m.group(1).decode("ascii").lower()
        name = _INTERNED_HEADERS.get(name_raw, name_raw)
        value = m.group(2).decode("latin-1")

        if name in headers:
            # Per RFC 7230 §3.2.2: only some headers (Set-Cookie etc.) may
            # legally repeat; for header types we care about for routing
            # (host, content-length, transfer-encoding) repetition is a
            # smuggling indicator.
            if name in _DUPLICATE_REJECT:
                raise ParseError(f"duplicate {name} header rejected")
            headers[name] = headers[name] + ", " + value
        else:
            headers[name] = value

    return RequestHead(
        method=method,
        path=path,
        query=query,
        http_version=(major, minor),
        headers=headers,
        raw_size=len(raw),
    )


def classify_body_framing(
    method: str,
    headers: dict[str, str],
) -> tuple[str, int | None]:
    """Decide how to read the request body.

    Returns ``(kind, content_length)`` where ``kind`` is one of:

    * ``"none"``      — no body expected (length 0 always returned).
    * ``"chunked"``   — body framed via Transfer-Encoding: chunked.
    * ``"fixed"``     — body framed via Content-Length; ``content_length`` set.
    """
    cl = headers.get("content-length")
    te = headers.get("transfer-encoding")

    if te is not None:
        # CL+TE both present → smuggling; reject per RFC 7230 §3.3.3 #3.
        if cl is not None:
            raise ParseError("Content-Length and Transfer-Encoding cannot both be present")
        # Only "chunked" is recognized by this server. Multiple
        # transfer-codings (e.g. "gzip, chunked") would require a different
        # decode path; for now reject as out-of-spec for this server.
        if te.strip().lower() != "chunked":
            raise ParseError(f"unsupported Transfer-Encoding: {te!r}", status_code=501)
        return "chunked", None

    if cl is not None:
        cl = cl.strip()
        if not _TOKEN_DIGITS.match(cl.encode("ascii")):
            raise ParseError("invalid Content-Length")
        length = int(cl)
        if length < 0:
            raise ParseError("negative Content-Length")
        return "fixed", length

    # Methods that customarily carry a body MUST declare framing.
    if method in ("POST", "PUT", "PATCH"):
        raise ParseError(
            f"missing Content-Length or Transfer-Encoding for {method}",
            status_code=411,
        )

    return "none", 0


ReadMore = Callable[[], Awaitable[None]]


async def read_body(
    kind: str,
    content_length: int | None,
    buffer: ReceiveBuffer,
    *,
    max_body_bytes: int,
    max_chunk_bytes: int,
    read_more: ReadMore,
) -> bytes:
    """Read the request body into a single ``bytes`` object, enforcing
    configured size limits. ``read_more`` is awaited whenever the buffer is
    exhausted; it is responsible for appending more bytes to ``buffer`` (or
    raising on EOF / timeout)."""
    if kind == "none":
        return b""
    if kind == "fixed":
        return await _read_fixed(buffer, content_length or 0, max_body_bytes, read_more)
    if kind == "chunked":
        return await _read_chunked(buffer, max_body_bytes, max_chunk_bytes, read_more)
    raise ParseError(f"unknown body framing: {kind}")


async def _read_fixed(
    buffer: ReceiveBuffer,
    length: int,
    max_body_bytes: int,
    read_more: ReadMore,
) -> bytes:
    if length > max_body_bytes:
        raise ParseError("request body too large", status_code=413)

    if length == 0:
        return b""

    out = bytearray()
    remaining = length
    while remaining > 0:
        chunk = buffer.maybe_extract_at_most(remaining)
        if chunk is None:
            await read_more()
            continue
        out.extend(chunk)
        remaining -= len(chunk)

    return bytes(out)


async def _read_chunked(
    buffer: ReceiveBuffer,
    max_body_bytes: int,
    max_chunk_bytes: int,
    read_more: ReadMore,
) -> bytes:
    out = bytearray()
    while True:
        size_line = buffer.maybe_extract_next_line()
        while size_line is None:
            await read_more()
            size_line = buffer.maybe_extract_next_line()

        # Strip trailing CRLF and any chunk-extensions (everything past `;`).
        line_view = bytes(size_line).rstrip(b"\r\n")
        sep = line_view.find(b";")
        size_part = (line_view if sep == -1 else line_view[:sep]).strip()
        if not size_part or not all(c in b"0123456789abcdefABCDEF" for c in size_part):
            raise ParseError("invalid chunk size")

        chunk_size = int(size_part, 16)
        if chunk_size > max_chunk_bytes:
            raise ParseError("chunk size exceeds limit", status_code=413)
        if len(out) + chunk_size > max_body_bytes:
            raise ParseError("chunked body exceeds limit", status_code=413)

        if chunk_size == 0:
            # Last chunk. Consume optional trailers + final CRLF.
            await _consume_chunked_trailers(buffer, read_more)
            return bytes(out)

        # Read exactly chunk_size bytes followed by exactly CRLF.
        remaining = chunk_size
        while remaining > 0:
            data = buffer.maybe_extract_at_most(remaining)
            if data is None:
                await read_more()
                continue
            out.extend(data)
            remaining -= len(data)

        # Trailing CRLF after the chunk data.
        crlf = buffer.maybe_extract_at_most(2)
        while crlf is None or len(crlf) < 2:
            await read_more()
            more = buffer.maybe_extract_at_most(2 - (0 if crlf is None else len(crlf)))
            if more is None:
                continue
            crlf = (crlf or bytearray()) + more
        if bytes(crlf) != b"\r\n":
            raise ParseError("missing CRLF after chunk data")


async def _consume_chunked_trailers(
    buffer: ReceiveBuffer,
    read_more: ReadMore,
) -> None:
    """Consume optional trailer headers and the terminating blank line. Drop
    trailer values — accepting them safely requires the server to also have
    declared TE: trailers in the response negotiation, which mkfst does not."""
    while True:
        line = buffer.maybe_extract_next_line()
        while line is None:
            await read_more()
            line = buffer.maybe_extract_next_line()
        if bytes(line).rstrip(b"\r\n") == b"":
            return
