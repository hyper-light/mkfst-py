from typing import Callable, Dict, Optional, Union

from pydantic import IPvAnyAddress

from mkfst.env import Env
from mkfst.logging import Logger, LogLevel
from mkfst.models.http import Limit
from mkfst.models.logging import Event

from .limiters import (
    AdaptiveRateLimiter,
    CPUAdaptiveLimiter,
    LeakyBucketLimiter,
    ResourceAdaptiveLimiter,
    SlidingWindowLimiter,
    TokenBucketLimiter,
)


class Limiter:
    def __init__(self, env: Env) -> None:
        self._limiter: Union[
            Union[
                AdaptiveRateLimiter,
                CPUAdaptiveLimiter,
                LeakyBucketLimiter,
                ResourceAdaptiveLimiter,
                SlidingWindowLimiter,
                TokenBucketLimiter,
            ],
            None,
        ] = None

        self._default_limit = Limit(
            max_requests=env.MERCURY_SYNC_HTTP_RATE_LIMIT_REQUESTS,
            request_period=env.MERCURY_SYNC_HTTP_RATE_LIMIT_PERIOD,
            reject_requests=env.MERCURY_SYNC_HTTP_RATE_LIMIT_DEFAULT_REJECT,
            cpu_limit=env.MERCURY_SYNC_HTTP_CPU_LIMIT,
            memory_limit=env.MERCURY_SYNC_HTTP_MEMORY_LIMIT,
        )

        self._rate_limit_strategy = env.MERCURY_SYNC_HTTP_RATE_LIMIT_STRATEGY
        self._default_limiter_type = env.MERCURY_SYNC_HTTP_RATE_LIMITER_TYPE

        self._rate_limiter_types: Dict[
            str,
            Callable[
                [Limit],
                Union[
                    AdaptiveRateLimiter,
                    CPUAdaptiveLimiter,
                    LeakyBucketLimiter,
                    ResourceAdaptiveLimiter,
                    SlidingWindowLimiter,
                    TokenBucketLimiter,
                ],
            ],
        ] = {
            "adaptive": AdaptiveRateLimiter,
            "cpu-adaptive": CPUAdaptiveLimiter,
            "leaky-bucket": LeakyBucketLimiter,
            "rate-adaptive": ResourceAdaptiveLimiter,
            "sliding-window": SlidingWindowLimiter,
            "token-bucket": TokenBucketLimiter,
        }

        self._rate_limit_period = env.MERCURY_SYNC_HTTP_RATE_LIMIT_PERIOD

        self._rate_limiters: Dict[
            str,
            Union[
                AdaptiveRateLimiter,
                CPUAdaptiveLimiter,
                LeakyBucketLimiter,
                SlidingWindowLimiter,
                TokenBucketLimiter,
            ],
        ] = {}

        self._logger = Logger()

    async def limit(
        self, 
        ip_address: IPvAnyAddress, 
        path: str, 
        method: str, 
        limit: Optional[Limit] = None
    ):
        async with self._logger.context(
            template="{timestamp} - {level} - {thread_id} - {message}",
        ) as ctx:
            
            rejected = False
            limit_type = limit.limiter_type if limit else self._default_limiter_type

            if limit is None:
                limit = self._default_limit
            
            await ctx.log(Event(
                level=LogLevel.DEBUG,
                message=f'Request - {method} {path}:{str(ip_address)} - Using {limit_type} rate limiter with strategy - {self._rate_limit_strategy}'
            ))
            
            limit_key: Union[str, None] = None

            if self._rate_limit_strategy == "ip":
                limit_key = limit.get_key(
                    path,
                    method, 
                    ip_address, 
                    default=ip_address
                )

            elif self._rate_limit_strategy == "endpoint":
                limit_key = limit.get_key(
                    path,
                    method, 
                    ip_address, 
                    default=path
                )

            elif self._rate_limit_strategy == "global":
                limit_key = self._default_limit.get_key(
                    path, 
                    method, 
                    ip_address, 
                    default="default",
                )

                limit = self._default_limit

            elif self._rate_limit_strategy == "ip-endpoint":
                limit_key = limit.get_key(
                    path,
                    method, 
                    ip_address, 
                    default=f"{path}_{ip_address}"
                )

            elif limit:
                limit_key = limit.get_key(
                    path, 
                    method, 
                    ip_address,
                )

            if limit_key and limit.matches(
                path,
                method, 
                ip_address,
            ):
                rejected = await self._check_limiter(
                    limit_key, 
                    limit,
                    path,
                    method,
                    ip_address,
                )

            if rejected:
                await ctx.log(Event(
                    level=LogLevel.DEBUG,
                    message=f'Request - {method} {path}:{str(ip_address)} - Request rejected by {limit.limiter_type} using strategy {self._rate_limit_strategy}'
                ))

            else:
                await ctx.log(Event(
                    level=LogLevel.DEBUG,
                    message=f'Request - {method} {path}:{str(ip_address)} - Request accepted by {limit.limiter_type} using strategy {self._rate_limit_strategy}'
                ))

            return rejected

    async def _check_limiter(
        self, 
        limiter_key: str, 
        limit: Limit,
        path: str,
        method: str,
        ip_address: IPvAnyAddress
    ):
        async with self._logger.context(
            template="{timestamp} - {level} - {thread_id} - {message}",
        ) as ctx:
            
            await ctx.log(Event(
                level=LogLevel.DEBUG,
                message=f'Request - {method} {path}:{str(ip_address)} - Checking  {limit.limiter_type} rate limiter with strategy - {self._rate_limit_strategy}'
            ))
            
            limiter = self._rate_limiters.get(limiter_key)

            rate_limiter_type = limit.limiter_type
            if rate_limiter_type is None:
                rate_limiter_type = self._default_limiter_type

            if limiter is None:
                limiter = self._rate_limiter_types.get(rate_limiter_type)(limit)

                self._rate_limiters[limiter_key] = limiter

            return await limiter.acquire()

    async def close(self):
        for limiter in self._rate_limiters.values():
            if isinstance(limiter, CPUAdaptiveLimiter):
                await limiter.close()

    def abort(self):
        for limiter in self._rate_limiters.values():
            if isinstance(limiter, CPUAdaptiveLimiter):
                limiter.abort()
