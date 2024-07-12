import asyncio
import math
import random
from typing import (
    Any,
    Optional,
    Union,
)

from mkfst.env import Env, load_env
from mkfst.env.time_parser import TimeParser
from mkfst.logging import Logger, LogLevel
from mkfst.middleware.base import Middleware, MiddlewareType
from mkfst.middleware.base.response_context import ResponseContext
from mkfst.middleware.base.types import Handler, MiddlewareHandler, MiddlewareResult
from mkfst.models.logging import Event
from mkfst.rate_limiting.limiters import SlidingWindowLimiter

from .circuit_breaker_state import CircuitBreakerState


class CircuitBreaker(Middleware):
    def __init__(
        self,
        failure_threshold: Optional[float] = None,
        failure_window: Optional[str] = None,
        handler_timeout: Optional[str] = None,
        rejection_sensitivity: Optional[float] = None,
    ) -> None:
        super().__init__(
            self.__class__.__name__, 
            middleware_type=MiddlewareType.CALL,
            response_headers={
                "x-mercury-sync-overload": True
            }
        )

        env = load_env(Env)

        self._logger = Logger()

        if failure_threshold is None:
            failure_threshold = env.MERCURY_SYNC_HTTP_CIRCUIT_BREAKER_FAILURE_THRESHOLD

        if failure_window is None:
            failure_window = env.MERCURY_SYNC_HTTP_CIRCUIT_BREAKER_FAILURE_WINDOW

        if handler_timeout is None:
            handler_timeout = env.MERCURY_SYNC_HTTP_HANDLER_TIMEOUT

        if rejection_sensitivity is None:
            rejection_sensitivity = (
                env.MERCURY_SYNC_HTTP_CIRCUIT_BREAKER_REJECTION_SENSITIVITY
            )

        self.failure_threshold = failure_threshold
        self.rejection_sensitivity = rejection_sensitivity

        self.failure_window = TimeParser(failure_window).time
        self.handler_timeout = TimeParser(handler_timeout).time
        self._limiter_failure_window = failure_window

        self.overload = 0
        self.failed = 0
        self.succeeded = 0
        self.total_completed = 0

        self._rate_per_sec = 0
        self._rate_per_sec_succeeded = 0
        self._rate_per_sec_failed = 0

        self._previous_count = 0
        self._previous_count_succeeded = 0
        self._previous_count_failed = 0

        self.wraps: bool = False

        self._loop: Union[asyncio.AbstractEventLoop, None] = None
        self._current_time: Union[float, None] = None
        self._breaker_state = CircuitBreakerState.CLOSED

        self._limiter: Union[SlidingWindowLimiter, None] = None

        self._closed_window_start: Union[float, None] = None
        self._closed_elapsed = 0

        self._half_open_window_start: Union[float, None] = None
        self._half_open_elapsed = 0

    def trip_breaker(self) -> bool:
        failed_rate_threshold = max(self._rate_per_sec * self.failure_threshold, 1)

        return int(self._rate_per_sec_failed) > int(failed_rate_threshold)

    def reject_request(self) -> bool:
        if (self._loop.time() - self._current_time) > self.failure_window:
            self._current_time = (
                math.floor(self._loop.time() / self.failure_window)
                * self.failure_window
            )

            self._previous_count = self.total_completed
            self._previous_count_succeeded = self.succeeded
            self._previous_count_failed = self.failed

            self.failed = 0
            self.succeeded = 0
            self.total_completed = 0

        self._rate_per_sec = (
            self._previous_count
            * (self.failure_window - (self._loop.time() - self._current_time))
            / self.failure_window
        ) + self.total_completed

        self._rate_per_sec_succeeded = (
            self._previous_count_succeeded
            * (self.failure_window - (self._loop.time() - self._current_time))
            / self.failure_window
        ) + self.succeeded

        self._rate_per_sec_failed = (
            self._previous_count_failed
            * (self.failure_window - (self._loop.time() - self._current_time))
            / self.failure_window
        ) + self.failed

        success_rate = self._rate_per_sec_succeeded / (1 - self.failure_threshold)

        rejection_probability = max(
            (self._rate_per_sec - success_rate) / (self._rate_per_sec + 1), 0
        ) ** (1 / self.rejection_sensitivity)

        return random.random() < rejection_probability

    async def __setup__(self):

        async with self._logger.context() as ctx:
            await ctx.log(Event(
                level=LogLevel.DEBUG,
                message=f'Setting up middleware - {self.__class__.__name__}',
            ))

            self._loop = asyncio.get_event_loop()
            self._current_time = self._loop.time()

    async def __run__(
        self, 
        context: ResponseContext | None = None,
        response: Any | None = None,
        handler: MiddlewareHandler | Handler | None = None,
    ) -> MiddlewareResult:
        reject = self.reject_request()

        async with self._logger.context(
            template="{timestamp} - {level} - {thread_id} - {message}",
        ) as ctx:
            
            await ctx.log(Event(
                level=LogLevel.DEBUG,
                message=f'Request - {context.method} {context.path}:{context.ip_address} - Entered circuit breaker current state - {self._breaker_state.value}',
            ))
            
            if (
                self._breaker_state == CircuitBreakerState.OPEN
                and self._closed_elapsed < self.failure_window
            ):
                self._closed_elapsed = self._loop.time() - self._closed_window_start
                reject = True

                await ctx.log(Event(
                    level=LogLevel.DEBUG,
                    message=f'Request - {context.method} {context.path}:{context.ip_address} - Not enough time has elapsed since failure state - rejecting request',
                ))

            elif self._breaker_state == CircuitBreakerState.OPEN:
                self._breaker_state = CircuitBreakerState.HALF_OPEN

                self._half_open_window_start = self._loop.time()
                self._closed_elapsed = 0

                await ctx.log(Event(
                    level=LogLevel.DEBUG,
                    message=f'Request - {context.method} {context.path}:{context.ip_address} - Setting breaker state from {CircuitBreakerState.OPEN.value} to {self._breaker_state.value}',
                ))

            if (
                self._breaker_state == CircuitBreakerState.HALF_OPEN
                and self._half_open_elapsed < self.failure_window
            ):
                self._half_open_elapsed = self._loop.time() - self._half_open_window_start

                await ctx.log(Event(
                    level=LogLevel.DEBUG,
                    message=f'Request - {context.method} {context.path}:{context.ip_address} - {self._half_open_elapsed} seconds elapsed since entered {self._breaker_state.value} state',
                ))

            elif self._breaker_state == CircuitBreakerState.HALF_OPEN:
                self._breaker_state = CircuitBreakerState.CLOSED
                self._half_open_elapsed = 0

                await ctx.log(Event(
                    level=LogLevel.DEBUG,
                    message=f'Request - {context.method} {context.path}:{context.ip_address} - Setting breaker state from {CircuitBreakerState.HALF_OPEN.value} to {self._breaker_state.value}',
                ))

                await ctx.log(Event(
                    level=LogLevel.WARN,
                    message=f'Request - {context.method} {context.path}:{context.ip_address} - Request tripped circuit breaker',
                ))

            if reject:
                context.response_headers["x-mercury-sync-overload"] = True
                context.status = 503

                await ctx.log(Event(
                    level=LogLevel.DEBUG,
                    message=f'Request - {context.method} {context.path}:{context.ip_address} - Rejecting request with status of {context.status}',
                ))

            else:
                try:

                    if self.wraps:

                        await ctx.log(Event(
                            level=LogLevel.DEBUG,
                            message=f'Request - {context.method} {context.path}:{context.ip_address} - Executing wrapped middleware {handler.__class__.__name__}',
                        ))

                        (context, response) = await asyncio.wait_for(
                            handler(
                                context=context,
                                response=response
                            ), 
                            timeout=self.handler_timeout
                        )

                        await ctx.log(Event(
                            level=LogLevel.DEBUG,
                            message=f'Request - {context.method} {context.path}:{context.ip_address} - {handler.__class__.__name__} completed middleware',
                        ))

                    else:

                        await ctx.log(Event(
                            level=LogLevel.DEBUG,
                            message=f'Request - {context.method} {context.path}:{context.ip_address} - Executing wrapped request handler',
                        ))

                        response = await asyncio.wait_for(
                            handler(
                                *context.args, 
                                **context.kwargs
                            ), 
                            timeout=self.handler_timeout
                        )

                        await ctx.log(Event(
                            level=LogLevel.DEBUG,
                            message=f'Request - {context.method} {context.path}:{context.ip_address} - Request handler completed execution',
                        ))
                    
                    context.response_headers["x-mercury-sync-overload"] = False

                except (
                    asyncio.TimeoutError,
                    asyncio.CancelledError,
                ):
                    context.response_headers["x-mercury-sync-overload"] = True
                    context.status = 503

                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {context.method} {context.path}:{context.ip_address} - Request timed out with status of {context.status}',
                    ))

                # Don't count rejections toward failure stats.
                if context.status and context.status >= 400:
                    self.failed += 1

                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {context.method} {context.path}:{context.ip_address} - Updated failed count {self.failed}',
                    ))

                elif context.status is None or (
                    context.status and context.status < 400
                ):
                    self.succeeded += 1

                    await ctx.log(Event(
                        level=LogLevel.DEBUG,
                        message=f'Request - {context.method} {context.path}:{context.ip_address} - Updated successful count {self.succeeded}',
                    ))

                self.total_completed += 1

                await ctx.log(Event(
                    level=LogLevel.DEBUG,
                    message=f'Request - {context.method} {context.path}:{context.ip_address} - Updated completed count {self.total_completed}',
                ))

            breaker_open = (
                self._breaker_state == CircuitBreakerState.CLOSED
                or self._breaker_state == CircuitBreakerState.HALF_OPEN
            )

            await ctx.log(Event(
                level=LogLevel.DEBUG,
                message=f'Request - {context.method} {context.path}:{context.ip_address} - Breaker state open is - {breaker_open}',
            ))

            if self.trip_breaker() and breaker_open:
                self._breaker_state = CircuitBreakerState.OPEN
                reject = True

                self._closed_window_start = self._loop.time()
                self._half_open_elapsed = 0

                await ctx.log(Event(
                    level=LogLevel.DEBUG,
                    message=f'Request - {context.method} {context.path}:{context.ip_address} - Resetting circuit breaker',
                ))

            if reject:
                await ctx.log(Event(
                    level=LogLevel.WARN,
                    message=f'Request - {context.method} {context.path}:{context.ip_address} - Circuit breaker rejected request',
                ))

                context.errors.append(Exception('Err. - request temporarily rejected.')) 

            return (
                context,
                response,
            ), reject is False

    async def close(self):
        await self._logger.close()

    def abort(self):
        self._logger.abort()