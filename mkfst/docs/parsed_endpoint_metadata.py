from typing import Dict, Literal

from pydantic import BaseModel, StrictStr

from .parsed_operation_metadata import ParsedOperationMetadata

HTTPMethod = Literal[
   "GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE", "TRACE"
]

class ParsedEndpointMetadata(BaseModel):
    description: StrictStr | None = None
    summary: StrictStr | None = None
    operations: Dict[HTTPMethod, ParsedOperationMetadata] = {}

    