from enum import Enum


class RequestState(Enum):
    PARSE = "PARSE"
    ROUTE = "ROUTE"
    RATE_LIMIT = "RATE_LIMIT"
    MIDDLEWARE = "MIDDLEWARE"
    HANDLE = "HANDLE"
    COMPLETE = "COMLPLETE"
    ERROR = "ERROR"
    ABORTED = "ABORTED"
