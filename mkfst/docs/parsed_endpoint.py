from typing import Any, Dict, List, Literal

from pydantic import BaseModel, StrictBytes, StrictInt, StrictStr

from mkfst.models import (
    HTML,
    Body,
    FileUpload,
    Headers,
    Parameters,
    Query,
    Model,
)

from .parsed_endpoint_metadata import (
    HTTPMethod,
    ParsedEndpointMetadata,
)


class ParsedEndpoint(BaseModel):
    path: StrictStr
    methods: List[HTTPMethod]
    endpoint_metadata: ParsedEndpointMetadata
    responses: Dict[
        StrictInt,
        type[HTML]
        | type[FileUpload]
        | type[Body]
        | type[Model]
        | type[dict]
        | type[list]
        | type[str]
        | type[bytes]
        | StrictStr
        | StrictBytes
        | None,
    ]
    response_headers: Dict[StrictStr, Any] | None = None
    headers: type[Headers] | None = None
    parameters: type[Parameters] | None = None
    query: type[Query] | None = None
    body: (
        type[HTML]
        | type[FileUpload]
        | type[Body]
        | type[Model]
        | type[dict]
        | type[list]
        | type[str]
        | type[bytes]
        | StrictStr
        | StrictBytes
        | None
    ) = None
    required: (
        List[
            Literal[
                "parameters",
                "headers",
                "query",
                "body",
            ]
        ]
        | None
    ) = None

    def to_dict(self):
        # Pydantic V2.11+ deprecated instance access of `model_fields`;
        # use the class accessor.
        return {field: getattr(self, field) for field in type(self).model_fields}
