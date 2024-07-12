from typing import (
    Any,
    Dict,
    List,
    Literal,
)

FieldType =Dict[
    Literal["type"],
    str
]

FieldMetadata = Dict[
    Literal["title", "type", "format", "description", "anyOf"] | str,
    str | int | Any | List[FieldType]
]

FieldsMetadata = Dict[str, FieldMetadata]
PropertyMetadata = Dict[
    Literal["properties", 'required'],
    FieldsMetadata | List[str]
]

SchemaType = Literal[
    "integer",
    "string",
    "boolean",
    "number",
    "array",
    "object",
]