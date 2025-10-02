from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    TypeVar,
    Union,
)

from pydantic import BaseModel

from .base_wrapper import BaseWrapper
from .response_context import ResponseContext
from .types import Handler, MiddlewareHandler, MiddlewareType

T = TypeVar("T")


class UnidirectionalWrapper(BaseWrapper):
    def __init__(
        self,
        name: str,
        handler: Handler,
        middleware_type: MiddlewareType = MiddlewareType.UNIDIRECTIONAL_BEFORE,
        methods: Optional[
            List[
                Literal[
                    "GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE", "TRACE"
                ]
            ]
        ] = None,
        responses: Optional[Dict[int, BaseModel]] = None,
        serializers: Optional[Dict[int, Callable[..., str]]] = None,
        response_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__()

        self.name = name
        self.path = handler.path
        self.methods: List[
            Literal["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE", "TRACE"]
        ] = handler.methods

        if methods:
            self.methods.extend(methods)

        self.response_headers: Union[Dict[str, str], None] = handler.response_headers

        if self.response_headers and response_headers:
            self.response_headers.update(response_headers)

        elif response_headers:
            self.response_headers = response_headers

        self.responses = responses
        self.serializers = serializers
        self.limit = handler.limit

        self.handler = handler
        self.wraps = isinstance(handler, BaseWrapper)

        # if self.handler.response_headers and self.response_headers:
        #     self.handler.response_headers = {}

        self.run: MiddlewareHandler | None = None
        self.middleware_type = middleware_type

    async def __call__(
        self,
        context: ResponseContext | None = None,
        response: Any | None = None,
    ):
        if context is None:
            raise Exception("Err. - Context is missing.")

        if self.wraps and self.middleware_type == MiddlewareType.UNIDIRECTIONAL_AFTER:
            # Is wraps additional middleware so expect
            # a middleware response.
            (context, response) = await self.handler(
                context=context,
                response=response,
            )

            (context, response), _ = await self.run(
                context=context,
                response=response,
                handler=self.handler,
            )

            return (
                context,
                response,
            )

        elif (
            self.wraps and self.middleware_type == MiddlewareType.UNIDIRECTIONAL_BEFORE
        ):
            # Wraps a call and should be executed before.

            (context, response), run_next = await self.run(
                context=context,
                response=response,
                handler=self.handler,
            )

            if run_next is False:
                return context, response

            (context, response) = await self.handler(
                context=context,
                response=response,
            )

            return (
                context,
                response,
            )

        elif self.middleware_type == MiddlewareType.UNIDIRECTIONAL_AFTER:
            # Wraps a call and should be executed after.

            response = await self.handler(*context.args, **context.kwargs)

            (context, response), _ = await self.run(
                context=context,
                response=response,
                handler=self.handler,
            )

            return (
                context,
                response,
            )

        else:
            (context, response), run_next = await self.run(
                context=context,
                response=response,
                handler=self.handler,
            )

            response = await self.handler(*context.args, **context.kwargs)

            return (
                context,
                response,
            )
