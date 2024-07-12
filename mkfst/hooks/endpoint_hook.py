import functools
from collections import defaultdict
from typing import (
    Dict,
    List,
    Literal,
    Optional,
    TypeVar,
    get_args,
    get_type_hints,
)

from pydantic import BaseModel

from mkfst.models.http import Limit

from .get_content_type import get_content_type

T = TypeVar("T")


def endpoint(
    path: Optional[str] = "/",
    methods: List[
        Literal[
            "GET", 
            "HEAD", 
            "OPTIONS", 
            "POST", "PUT", 
            "PATCH", 
            "DELETE", 
            "TRACE",
        ],
    ] = ["GET"],
    responses: Optional[Dict[int, BaseModel]] = None,
    response_headers: Optional[Dict[str, str]] = None,
    limit: Optional[Limit] = None,
    summary: str | None = None,
    tags: List[str] | None = None,
    method_metadata: Dict[
        Literal[
            "GET", 
            "HEAD", 
            "OPTIONS", 
            "POST", "PUT", 
            "PATCH", 
            "DELETE", 
            "TRACE",
        ],
        Dict[
            Literal[
                'name',
                'tags',
                'description',
                'summary',
                'docs_url',
                'docs_description',
                'depreciated',
            ],
            str | List[str] | bool
        ]
    ] | None = None,
    additional_docs: Dict[
        Literal[
            'doc_description',
            'docs_url'
        ],
        str
    ] | None = None,
    depreciated: bool = False
):

    def wraps(func):

        return_type = get_type_hints(func).get('return')
        return_args = get_args(return_type)

        if isinstance(return_args, tuple) and len(return_args) > 0:
            return_type = return_args[0]

        headers = response_headers or {}

        lowered_headers: Dict[str, str] = {}
        lowered_headers = {
            key.lower(): value.lower() for key, value in headers.items()
        }

        if lowered_headers.get('content-type') is None:
            headers.update({
                'content-type': get_content_type(return_type)
            })
            
        func.as_endpoint = True
        func.path = path
        func.methods = methods
        
        func.response_headers = headers
        func.responses = responses
        func.limit = limit
        func.summary = summary
        func.tags = tags
        func.method_metadata = method_metadata or defaultdict(dict)
        func.additional_docs = additional_docs,
        func.depreciated = depreciated


        @functools.wraps(func)
        def decorator(*args, **kwargs):
            return func(*args, **kwargs)

        return decorator

    return wraps
