from typing import Callable, List, Literal, Optional, Union

from pydantic import (
    BaseModel,
    IPvAnyAddress,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
)

from mkfst.env.memory_parser import MemoryParser
from mkfst.env.time_parser import TimeParser

HTTPMethod = Literal[
    "GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE", "TRACE"
]


class Limit(BaseModel):
    max_requests: Optional[StrictInt] = 1000
    min_requests: Optional[StrictInt] = 100
    request_period: StrictStr = "1s"
    reject_requests: StrictBool = True
    request_backoff: StrictStr = "1s"
    cpu_limit: Optional[Union[StrictFloat, StrictInt]] = None
    memory_limit: Optional[StrictStr] = None
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
                IPvAnyAddress,
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
                    IPvAnyAddress,
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
        ip_address: IPvAnyAddress, 
        default: str = "default"
    ):
        if self.limit_key is None:
            return default

        return self.limit_key(path, method, ip_address)

    def matches(
        self,
        path,
        method, 
        ip_address: IPvAnyAddress
    ):
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
