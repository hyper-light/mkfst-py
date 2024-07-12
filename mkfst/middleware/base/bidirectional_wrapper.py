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
from .types import (
    BidirectionalMiddlewareHandler,
    Handler,
    MiddlewareHandler,
    MiddlewareType,
)

T = TypeVar("T")


class BidirectionalWrapper(BaseWrapper):
    def __init__(
        self,
        name: str,
        handler: Handler | MiddlewareHandler,
        middleware_type: MiddlewareType = MiddlewareType.BIDIRECTIONAL,
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

        if self.response_headers:
            handler.response_headers.update(self.response_headers)

        self.handler = handler
        self.wraps = isinstance(handler, BaseWrapper)

        self.pre: Optional[BidirectionalMiddlewareHandler] = None
        self.post: Optional[BidirectionalMiddlewareHandler] = None

        self.middleware_type = middleware_type

    async def __call__(
        self,  
        context: ResponseContext | None = None,
        response: Any | None = None,
    ):
        if context is None:
            raise Exception('Err. - Context is missing.')

        (
            context, 
            response
        ), run_next = await self.pre(
            context=context,
            response=response,
            handler=self.handler,
        )

        if run_next is False:
            return context, response

        if self.wraps:
            # Is wraps additional middleware so expect
            # a middleware response
            ( 
                context, 
                response
            ) = await self.handler(
                context=context,
                response=response,
            )

        else:
            # Wraps the call so return the call response.
            response = await self.handler(
                *context.args,
                **context.kwargs,
            )

        (
            context, 
            response,
        ), _ = await self.post(
            context=context,
            response=response,
            handler=self.handler,
        )

        return (
            context, 
            response,
        )
