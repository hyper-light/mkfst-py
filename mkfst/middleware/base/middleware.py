from __future__ import annotations

from typing import (
    Any,
    Dict,
    List,
    Literal,
    Optional,
)

from mkfst.middleware.base.response_context import ResponseContext
from mkfst.middleware.base.types import (
    CallHandler,
    Handler,
    MiddlewareHandler,
    MiddlewareResult,
)

from .bidirectional_wrapper import BidirectionalWrapper
from .call_wrapper import CallWrapper
from .types import MiddlewareType
from .unidirectional_wrapper import UnidirectionalWrapper


class Middleware:
    def __init__(
        self,
        name: str,
        middleware_type: MiddlewareType = MiddlewareType.UNIDIRECTIONAL_BEFORE,
        methods: Optional[
            List[
                Literal[
                    "GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE", "TRACE"
                ]
            ]
        ] = None,
        response_headers: Dict[str, str] | None = None,
    ) -> None:
        if response_headers is None:
            response_headers = {}

        self.name = name
        self.methods = methods
        self.response_headers = response_headers
        self.middleware_type = middleware_type
        self.wraps = False

        self._wrapper_types = {
            MiddlewareType.BIDIRECTIONAL: BidirectionalWrapper,
            MiddlewareType.CALL: CallWrapper,
            MiddlewareType.UNIDIRECTIONAL_BEFORE: UnidirectionalWrapper,
            MiddlewareType.UNIDIRECTIONAL_AFTER: UnidirectionalWrapper,
        }

    def __call__(
        self,
        context: ResponseContext | None = None,
        response: Any | None = None,
    ) -> MiddlewareResult:
        raise NotImplementedError(
            "Err. __call__() should not be called on base Middleware class."
        )

    def wrap(self, handler: CallHandler):
        wrapper = self._wrapper_types.get(
            self.middleware_type,
            BidirectionalWrapper(
                self.name,
                handler,
                methods=self.methods,
                response_headers=self.response_headers,
                middleware_type=self.middleware_type,
            ),
        )(
            self.name,
            handler,
            methods=self.methods,
            response_headers=self.response_headers,
            middleware_type=self.middleware_type,
        )

        if isinstance(wrapper, BidirectionalWrapper):
            wrapper.pre = self.__pre__
            wrapper.post = self.__post__

        elif isinstance(wrapper, (CallWrapper, UnidirectionalWrapper)):
            wrapper.run = self.__run__

        wrapper.setup = self.__setup__
        self.wraps = wrapper.wraps

        return wrapper

    async def __setup__(self):
        pass

    async def __pre__(
        self,
        context: ResponseContext | None = None,
        response: Any | None = None,
        handler: MiddlewareHandler | Handler | None = None,
    ) -> MiddlewareResult:
        raise NotImplementedError(
            "Err. - __pre__() is not implemented for base Middleware class."
        )

    async def __post__(
        self,
        context: ResponseContext | None = None,
        response: Any | None = None,
        handler: MiddlewareHandler | Handler | None = None,
    ) -> MiddlewareResult:
        raise NotImplementedError(
            "Err. - __post__() is not implemented for base Middleware class."
        )

    async def __run__(
        self,
        context: ResponseContext | None = None,
        response: Any | None = None,
        handler: MiddlewareHandler | Handler | None = None,
    ) -> MiddlewareResult:
        raise NotImplementedError(
            "Err. - __run__() is not implemented for base Middleware class."
        )

    async def run(self, *args, **kwargs):
        raise NotImplementedError(
            "Err. - middleware() is not implemented for base Middleware class."
        )

    async def close(self):
        raise NotImplementedError(
            "Err. - close() is not implemented for base Middleware class."
        )

    def abort(self):
        raise NotImplementedError(
            "Err. - abort() is not implemented for base Middleware class."
        )
