from __future__ import annotations

import pytest

from mkfst.connection.tcp.router import RouteError, Router


def test_basic_match() -> None:
    r = Router()
    r.add("api/users", {"GET": "list_users"})
    result = r.match("api/users")
    assert result is not None
    assert result.anything == {"GET": "list_users"}
    assert result.route == "api/users"


def test_var_match() -> None:
    r = Router()
    r.add("api/users/:id", {"GET": "get_user"})
    result = r.match("api/users/42")
    assert result is not None
    assert result.params == {"id": "42"}
    assert result.anything == {"GET": "get_user"}


def test_no_match_returns_none() -> None:
    r = Router()
    r.add("api/users", {"GET": "list_users"})
    assert r.match("api/missing") is None


def test_duplicate_route_rejected() -> None:
    """Pre-fix the second add silently overwrote the first; mkfst handed
    out the wrong handler with no signal to the developer."""
    r = Router()
    r.add("api/users", {"GET": "first"})
    with pytest.raises(RouteError, match="duplicate route"):
        r.add("api/users", {"GET": "second"})


def test_negative_match_invalidated_after_add() -> None:
    """Pre-fix the lru_cache cached the negative match and never saw the
    subsequent registration; the route was effectively unreachable."""
    r = Router()
    assert r.match("api/items") is None
    r.add("api/items", {"GET": "list"})
    result = r.match("api/items")
    assert result is not None
    assert result.anything == {"GET": "list"}


def test_positive_match_invalidated_after_add() -> None:
    r = Router()
    r.add("api/users/:id", {"GET": "first"})
    assert r.match("api/users/1") is not None
    r.add("api/orders", {"GET": "second"})
    # First route still resolves correctly after the second registration.
    assert r.match("api/users/1") is not None
    assert r.match("api/orders") is not None


def test_separate_routers_have_independent_caches() -> None:
    """Pre-fix the @lru_cache was bound to the unbound method, so all
    Router instances shared one cache. Two routers with disjoint route sets
    would alias each other's matches."""
    a = Router()
    b = Router()
    a.add("api/a", {"GET": "a"})
    b.add("api/b", {"GET": "b"})
    assert a.match("api/a").anything == {"GET": "a"}
    assert a.match("api/b") is None
    assert b.match("api/a") is None
    assert b.match("api/b").anything == {"GET": "b"}


def test_match_cache_size_does_not_throw_on_overflow() -> None:
    r = Router(cache_size=4)
    r.add("api/items/:id", {"GET": "x"})
    # Hammer the cache past its limit.
    for i in range(50):
        r.match(f"api/items/{i}")
    assert r.match("api/items/0") is not None


def test_var_any_match() -> None:
    r = Router()
    r.add("assets/:*path", {"GET": "static"})
    result = r.match("assets/css/main.css")
    assert result is not None
    assert result.params == {"path": ("css", "main.css")}
