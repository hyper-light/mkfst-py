from typing import Callable, List, Literal, Optional, Union
import msgspec
from ipaddress import IPv4Address, IPv6Address
from mkfst.env.memory_parser import MemoryParser
from mkfst.env.time_parser import TimeParser

HTTPMethod = Literal[
    "GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE", "TRACE"
]


class Limit(msgspec.Struct):
    max_requests: int = 1000
    min_requests: int = 100
    request_period: str = "1s"
    reject_requests: bool = True
    request_backoff: str = "1s"
    cpu_limit: float | int | None = None
    memory_limit: str = None
    limiter_type: Literal[
        "adaptive",
        "cpu-adaptive",
        "leaky-bucket",
        "rate-adaptive",
        "sliding-window",
        "token-bucket",
    ] = "sliding-window"
    limit_key: Optional[
        Callable[
            [
                str,
                str,
                IPv4Address | IPv6Address,
            ],
            str,
        ]
    ] = None
    rules: Optional[
        List[
            Callable[
                [
                    str,
                    str,
                    IPv4Address | IPv6Address,
                ],
                bool,
            ]
        ]
    ] = None

    @property
    def backoff(self):
        return TimeParser(self.request_backoff).time

    @property
    def period(self):
        return TimeParser(self.request_period).time

    @property
    def memory(self):
        return MemoryParser(self.memory_limit).megabytes(accuracy=4)

    def get_key(
        self,
        path: str,
        method: str,
        ip_address: IPv4Address | IPv6Address,
        default: str = "default",
    ):
        if self.limit_key is None:
            return default

        return self.limit_key(path, method, ip_address)

    def matches(self, path, method, ip_address: IPv4Address | IPv6Address):
        if self.rules is None:
            return True

        matches_rules = False

        for rule in self.rules:
            matches_rules = rule(
                path,
                method,
                ip_address,
            )

        return matches_rules
