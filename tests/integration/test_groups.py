"""End-to-end tests for nested Groups.

Pre-fix `Group._assemble` mutated each child group's `_base` in place via
``group._base = join_paths(self._base, group._base)``. That made
``_assemble`` non-idempotent: re-running setup or reusing the same `Group`
instance under another parent accumulated path prefixes (``/api/v1/users``
became ``/api/v1/api/v1/users`` on the second pass)."""

from __future__ import annotations

from mkfst import Group, Service, endpoint


class UsersGroup(Group):
    @endpoint("/get")
    async def get(self) -> dict:
        return {"resource": "user"}


class V1Group(Group):
    pass


class V2Group(Group):
    pass


class _NestedService(Service):
    pass


async def test_nested_group_prefix_resolves(service) -> None:
    handle = await service(
        _NestedService,
        groups=[
            V1Group("/api/v1", groups=[UsersGroup("/users")]),
        ],
    )
    r = await handle.client.get("/api/v1/users/get")
    assert r.status_code == 200, r.text
    assert r.json() == {"resource": "user"}


async def test_two_independent_group_subtrees_use_correct_prefix(service) -> None:
    """The same UsersGroup *class* is instantiated under two parents; pre-
    fix the in-place mutation would double-prefix one of the two."""
    handle = await service(
        _NestedService,
        groups=[
            V1Group("/api/v1", groups=[UsersGroup("/users")]),
            V2Group("/api/v2", groups=[UsersGroup("/users")]),
        ],
    )
    a = await handle.client.get("/api/v1/users/get")
    b = await handle.client.get("/api/v2/users/get")
    assert a.status_code == 200, a.text
    assert b.status_code == 200, b.text
    assert a.json() == b.json() == {"resource": "user"}


async def test_repeated_assemble_does_not_double_prefix(service) -> None:
    """Re-running setup on the same Group instance must produce the same
    routes both times."""
    inner = UsersGroup("/users")
    outer = V1Group("/api/v1", groups=[inner])
    handle = await service(_NestedService, groups=[outer])
    r = await handle.client.get("/api/v1/users/get")
    assert r.status_code == 200, r.text
    # The inner group's own base should still be the literal "/users", not
    # the joined "/api/v1/users".
    assert inner._base == "/users"
