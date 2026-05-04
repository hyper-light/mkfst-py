"""Exercise handler signatures with non-trivial parameter shapes.

These tests would have caught the entire fabricator bug cluster prior to fix:
position-0 Headers misclassification, dead cookie branch, query positional
flag using the wrong key, Query.make inversion, etc.
"""

from __future__ import annotations

from mkfst import Cookies, Headers, Model, Query, Service, endpoint


class _Echo(Model):
    msg: str
    n: int = 0


class _MyHeaders(Headers):
    x_request_id: str | None = None
    user_agent: str | None = None


class _MyCookies(Cookies):
    session: str | None = None


class _MyQuery(Query):
    q: str | None = None
    page: str | None = None


class _MyBody(Model):
    name: str
    count: int


class _ShapesService(Service):
    @endpoint("/headers-first", methods=["POST"])
    async def headers_first(
        self,
        headers: _MyHeaders,
        body: _MyBody,
    ) -> _Echo:
        return _Echo(msg=f"hello {body.name}", n=body.count)

    @endpoint("/query")
    async def query_only(self, query: _MyQuery) -> _Echo:
        return _Echo(msg=query.q or "", n=int(query.page or 0))

    @endpoint("/cookies")
    async def cookies_only(self, cookies: _MyCookies) -> _Echo:
        return _Echo(msg=cookies.session or "no-session", n=0)

    @endpoint("/everything", methods=["POST"])
    async def everything(
        self,
        headers: _MyHeaders,
        body: _MyBody,
        cookies: _MyCookies,
        query: _MyQuery,
    ) -> _Echo:
        return _Echo(
            msg=f"{body.name}|{query.q}|{cookies.session or '-'}|{headers.x_request_id or '-'}",
            n=body.count,
        )


async def test_headers_at_position_0_dispatches(service) -> None:
    """Pre-fix the Headers parameter at position 0 was classified as keyword
    and the handler crashed at dispatch time."""
    handle = await service(_ShapesService)
    r = await handle.client.post(
        "/headers-first",
        json={"name": "alice", "count": 7},
        headers={"x-request-id": "abc"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"msg": "hello alice", "n": 7}


async def test_query_parameters_actually_parsed(service) -> None:
    """Pre-fix Query.make's `if len(query) < 1:` was inverted and parsed
    only when the query was empty, leaving every param missing."""
    handle = await service(_ShapesService)
    r = await handle.client.get("/query", params={"q": "search-term", "page": "3"})
    assert r.status_code == 200, r.text
    assert r.json() == {"msg": "search-term", "n": 3}


async def test_cookies_actually_parsed(service) -> None:
    """Pre-fix the cookie branch was guarded by `if self._cookie_key_type and
    cookies` where `cookies` was always None, so the branch never ran."""
    handle = await service(_ShapesService)
    handle.client.cookies.set("session", "abc-123")
    r = await handle.client.get("/cookies")
    assert r.status_code == 200, r.text
    assert r.json() == {"msg": "abc-123", "n": 0}


async def test_combined_handler_with_all_shapes(service) -> None:
    """All four parameter kinds in one handler — exercises the full fabricator
    matrix end-to-end."""
    handle = await service(_ShapesService)
    handle.client.cookies.set("session", "tok")
    r = await handle.client.post(
        "/everything",
        json={"name": "bob", "count": 5},
        headers={"x-request-id": "req-1"},
        params={"q": "term"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n"] == 5
    parts = body["msg"].split("|")
    assert parts[0] == "bob"
    assert parts[1] == "term"
    assert parts[2] == "tok"
    assert parts[3] == "req-1"
