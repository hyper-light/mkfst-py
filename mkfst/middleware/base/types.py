from enum import Enum
from typing import (
    Any,
    Callable,
    Coroutine,
    Dict,
    Tuple,
    Union,
)

from .response_context import ResponseContext

PositionalArgs = Tuple[Any, ...]
KeywordArgs = Dict[str, Any]

class MiddlewareType(Enum):
    BIDIRECTIONAL = "BIDIRECTIONAL"
    CALL = "CALL"
    UNIDIRECTIONAL_BEFORE = "UNIDIRECTIONAL_BEFORE"
    UNIDIRECTIONAL_AFTER = "UNIDIRECTIONAL_AFTER"

MiddlewareResult = Tuple[ResponseContext, Any]
RunResult = Tuple[MiddlewareResult, bool]

RequestHandler = Callable[
    ..., 
    Coroutine[Any, Any, Any]
]

WrappedHandler = Callable[
    ..., 
    Coroutine[Any, Any, Any]
]

CallHandler = Callable[
    ..., 
    Coroutine[Any, Any, Any]
]

MiddlewareHandler = Callable[
    ..., 
    Coroutine[Any, Any, RunResult]
]


BidirectionalMiddlewareHandler = Callable[
    [
        ResponseContext,
        Any,
        CallHandler | MiddlewareHandler
    ],
    Coroutine[
        Any, 
        Any, 
        Tuple[
            MiddlewareResult, 
            bool
        ]
    ],
]


Handler = Union[RequestHandler, WrappedHandler]
