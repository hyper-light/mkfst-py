from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import AsyncIterator, Awaitable, Callable

import httpx
import pytest
import pytest_asyncio


def _alloc_port() -> int:
    """Reserve a free TCP port on localhost. Closes the probe socket immediately
    so the caller can rebind it. Brief race window is acceptable for tests."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def free_port() -> int:
    return _alloc_port()


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force tests to provide an explicit auth secret of sufficient entropy.
    Default secret is invalid; tests that don't override it must not touch
    encryption-dependent code paths."""
    monkeypatch.setenv(
        "MERCURY_SYNC_AUTH_SECRET",
        os.environ.get(
            "MERCURY_SYNC_AUTH_SECRET",
            "test-secret-bytes-32-chars-long!!",
        ),
    )
    monkeypatch.setenv("MERCURY_SYNC_LOG_LEVEL", "error")


@pytest_asyncio.fixture(autouse=True)
async def _close_loggers():
    """Drain and close any Logger instances created during a test so the dup'd
    stdout/stderr file objects don't leak as ResourceWarnings."""
    yield
    # Walk live Logger instances tracked via the LoggerContext registry.
    from mkfst.logging.streams.logger import Logger as _Logger

    for instance in list(_Logger.__dict__.get("_test_instances", [])):
        try:
            await instance.close()
        except Exception:
            pass


ServiceFactory = Callable[..., Awaitable["ServiceHandle"]]


class ServiceHandle:
    """Wrapper around a running mkfst Service exposing an httpx client and
    deterministic teardown."""

    __slots__ = ("server", "host", "port", "_task", "client", "_base_url")

    def __init__(self, server, host: str, port: int, task: asyncio.Task[None]) -> None:
        self.server = server
        self.host = host
        self.port = port
        self._task = task
        self._base_url = f"http://{host}:{port}"
        self.client: httpx.AsyncClient = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(5.0, connect=2.0),
            transport=httpx.AsyncHTTPTransport(retries=0),
        )

    @property
    def base_url(self) -> str:
        return self._base_url

    async def aclose(self) -> None:
        await self.client.aclose()
        try:
            await asyncio.wait_for(self.server.close(), timeout=5.0)
        except (TimeoutError, AttributeError, asyncio.CancelledError, Exception):
            pass
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):
            pass


async def _wait_until_listening(host: str, port: int, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    last_err: BaseException | None = None
    while asyncio.get_running_loop().time() < deadline:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return
        except (ConnectionRefusedError, OSError) as e:
            last_err = e
            await asyncio.sleep(0.02)
    raise TimeoutError(
        f"Server at {host}:{port} did not start within {timeout}s (last error: {last_err!r})"
    )


@pytest_asyncio.fixture
async def service() -> AsyncIterator[ServiceFactory]:
    """Yields an async factory that constructs and starts a `Service`,
    waits for it to accept connections, and tears it down at test end."""

    handles: list[ServiceHandle] = []

    async def _factory(service_cls, *, host: str = "127.0.0.1", port: int | None = None, **kwargs):
        actual_port = port if port is not None else _alloc_port()
        kwargs.setdefault("workers", 0)
        kwargs.setdefault("log_level", "error")
        srv = service_cls(host, actual_port, **kwargs)
        task = asyncio.create_task(srv.run(), name=f"mkfst-test-{actual_port}")
        try:
            await _wait_until_listening(host, actual_port)
        except Exception:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            raise
        handle = ServiceHandle(srv, host, actual_port, task)
        handles.append(handle)
        return handle

    try:
        yield _factory
    finally:
        for h in handles:
            await h.aclose()
