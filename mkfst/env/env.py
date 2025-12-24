from __future__ import annotations
import os
import hyperjson
import msgspec
from ipaddress import IPv4Address, IPv6Address
from typing import Callable, Dict, Literal, Union

PrimaryType = Union[str, int, float, bytes, bool]


class Env(msgspec.Struct, kw_only=True):
    MERCURY_SYNC_SERVER_URL: str | None = None
    MERCURY_SYNC_API_VERISON: str = "0.0.1"
    MERCURY_SYNC_TASK_EXECUTOR_TYPE: Literal["thread", "process", "none"] = "process"
    MERCURY_SYNC_HTTP_CIRCUIT_BREAKER_REJECTION_SENSITIVITY: float = 2
    MERCURY_SYNC_HTTP_CIRCUIT_BREAKER_FAILURE_WINDOW: str = "1m"
    MERCURY_SYNC_HTTP_CIRCUIT_BREAKER_FAILURE_THRESHOLD: Union[int, float] = 0.2
    MERCURY_SYNC_HTTP_HANDLER_TIMEOUT: str = "1m"
    MERCURY_SYNC_HTTP_RATE_LIMIT_STRATEGY: Literal[
        "none", "global", "endpoint", "ip", "ip-endpoint", "custom"
    ] = "none"
    MERCURY_SYNC_HTTP_RATE_LIMITER_TYPE: Literal[
        "adaptive",
        "cpu-adaptive",
        "leaky-bucket",
        "rate-adaptive",
        "sliding-window",
        "token-bucket",
    ] = "sliding-window"
    MERCURY_SYNC_HTTP_CORS_ENABLED: bool = False
    MERCURY_SYNC_HTTP_MEMORY_LIMIT: str = "512mb"
    MERCURY_SYNC_HTTP_CPU_LIMIT: Union[float, int] = 50
    MERCURY_SYNC_HTTP_RATE_LIMIT_BACKOFF_RATE: int = 10
    MERCURY_SYNC_HTTP_RATE_LIMIT_BACKOFF: str = "1s"
    MERCURY_SYNC_HTTP_RATE_LIMIT_PERIOD: str = "1s"
    MERCURY_SYNC_HTTP_RATE_LIMIT_REQUESTS: int = 100
    MERCURY_SYNC_HTTP_RATE_LIMIT_STRATEGY: Literal[
        "ip",
        "endpoint",
        "global",
        "ip-endpoint",
        "none",
    ] = "none"
    MERCURY_SYNC_HTTP_RATE_LIMIT_DEFAULT_REJECT: bool = True
    MERCURY_SYNC_USE_HTTP_MSYNC_ENCRYPTION: bool = False
    MERCURY_SYNC_USE_HTTP_SERVER: bool = True
    MERCURY_SYNC_USE_HTTP_AND_TCP_SERVERS: bool = False
    MERCURY_SYNC_USE_UDP_MULTICAST: bool = False
    MERCURY_SYNC_TCP_CONNECT_RETRIES: int = 3
    MERCURY_SYNC_CLEANUP_INTERVAL: str = "0.25s"
    MERCURY_SYNC_MAX_CONCURRENCY: int = 2048
    MERCURY_SYNC_AUTH_SECRET: str = "testtoken"
    MERCURY_SYNC_MULTICAST_GROUP: IPv4Address | IPv6Address = "224.1.1.1"
    MERCURY_SYNC_LOGS_DIRECTORY: str = os.getcwd()
    MERCURY_SYNC_REQUEST_TIMEOUT: str = "30s"
    MERCURY_SYNC_LOG_LEVEL: str = "info"
    MERCURY_SYNC_TASK_RUNNER_MAX_THREADS: int = os.cpu_count()
    MERCURY_SYNC_MAX_REQUEST_CACHE_SIZE: int = 100
    MERCURY_SYNC_ENABLE_REQUEST_CACHING: bool = False
    MERCURY_SYNC_VERIFY_SSL_CERT: Literal["REQUIRED", "OPTIONAL", "NONE"] = "REQUIRED"

    @classmethod
    def types_map(cls) -> Dict[str, Callable[[str], PrimaryType]]:
        return {
            "MERCURY_SYNC_SERVER_URL": str,
            "MERCURY_SYNC_API_VERISON": str,
            "MERCURY_SYNC_TASK_EXECUTOR_TYPE": str,
            "MERCURY_SYNC_HTTP_CIRCUIT_BREAKER_REJECTION_SENSITIVITY": float,
            "MERCURY_SYNC_HTTP_CIRCUIT_BREAKER_FAILURE_WINDOW": str,
            "MERCURY_SYNC_HTTP_HANDLER_TIMEOUT": str,
            "MERCURY_SYNC_USE_UDP_MULTICAST": lambda value: True
            if value.lower() == "true"
            else False,
            "MERCURY_SYNC_HTTP_CIRCUIT_BREAKER_FAILURE_THRESHOLD": float,
            "MERCURY_SYNC_HTTP_CORS_ENABLED": lambda value: True
            if value.lower() == "true"
            else False,
            "MERCURY_SYNC_HTTP_MEMORY_LIMIT": str,
            "MERCURY_SYNC_HTTP_RATE_LIMIT_BACKOFF_RATE": int,
            "MERCURY_SYNC_HTTP_RATE_LIMIT_BACKOFF": str,
            "MERCURY_SYNC_HTTP_CPU_LIMIT": float,
            "MERCURY_SYNC_HTTP_RATE_LIMIT_STRATEGY": str,
            "MERCURY_SYNC_HTTP_RATE_LIMIT_PERIOD": str,
            "MERCURY_SYNC_HTTP_RATE_LIMIT_REQUESTS": int,
            "MERCURY_SYNC_HTTP_RATE_LIMIT_DEFAULT_REJECT": lambda value: True
            if value.lower() == "true"
            else False,
            "MERCURY_SYNC_USE_HTTP_MSYNC_ENCRYPTION": lambda value: True
            if value.lower() == "true"
            else False,
            "MERCURY_SYNC_USE_HTTP_SERVER": lambda value: True
            if value.lower() == "true"
            else False,
            "MERCURY_SYNC_TCP_CONNECT_RETRIES": int,
            "MERCURY_SYNC_CLEANUP_INTERVAL": str,
            "MERCURY_SYNC_MAX_CONCURRENCY": int,
            "MERCURY_SYNC_AUTH_SECRET": str,
            "MERCURY_SYNC_MULTICAST_GROUP": str,
            "MERCURY_SYNC_LOGS_DIRECTORY": str,
            "MERCURY_SYNC_REQUEST_TIMEOUT": str,
            "MERCURY_SYNC_LOG_LEVEL": str,
            "MERCURY_SYNC_TASK_RUNNER_MAX_THREADS": int,
            "MERCURY_SYNC_MAX_REQUEST_CACHE_SIZE": int,
            "MERCURY_SYNC_ENABLE_REQUEST_CACHING": str,
        }

    def model_dump(self, exclude_none: bool = False):
        if exclude_none:
            return {
                key: value
                for key, value in msgspec.structs.asdict(self)
                if value is not None
            }

        return msgspec.structs.asdict(self)

    def model_dump_json(self, exclude_none: bool = False):
        if exclude_none:
            return hyperjson.dumps(
                {
                    key: value
                    for key, value in msgspec.structs.asdict(self)
                    if value is not None
                }
            )

        return hyperjson.dumps(msgspec.structs.asdict(self))
