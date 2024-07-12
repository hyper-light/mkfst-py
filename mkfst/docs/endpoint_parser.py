import re
from typing import (
    Any,
    Dict,
    List,
    Literal,
    Set,
)

from pydantic import BaseModel, RootModel

from mkfst.models import (
    HTML,
    Body,
    FileUpload,
    Headers,
    InternalErrorSet,
    Parameters,
    Query,
)
from mkfst.models.http.request_models import HTTPEncodable
from mkfst.models.validation import ValidationErrorGroup

from .models import (
    Header,
    MediaType,
    Operation,
    Parameter,
    PathItem,
    RequestBody,
    Response,
)
from .parse_param import parse_param
from .parsed_endpoint_metadata import (
    HTTPMethod,
    ParsedEndpointMetadata,
)
from .parsed_operation_metadata import ParsedOperationMetadata
from .parsed_tag import ParsedTag

JSON = Dict[HTTPEncodable, HTTPEncodable] | List[HTTPEncodable]
REF_TEMPLATE = "#/components/schemas/{model}"

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
    Literal["properties"],
    FieldsMetadata
]

SchemaType = Literal[
    "integer",
    "string",
    "boolean",
    "number",
    "array",
    "object",
]

ParamType = (
    type[Parameter]
    | type[Header]
    | type[Query]
)

def parse_type(field: FieldMetadata) -> List[str] | str:
    field_data: List[FieldType] = field.get("anyOf")
    if field_data:
        return [
            field_type.get("type") for field_type in field_data
        ]
    
    return field.get("type", "string")


def parse_response_header_type(value: HTTPEncodable):
    if isinstance(value, int):
        return "integer"
    
    elif isinstance(value, float):
        return "number"
    
    elif isinstance(value, bool):
        return "boolean"
    
    else:
        return "string"
    

def parse_response_description(
    response: Any,
    status_code: int
):
    response_description = f'Response for status code {status_code}'
    if response in BaseModel.__subclasses__() and response.__doc__:
        response_description = response.__doc__

    return response_description


class EndpointParser:

    def __init__(
        self,
        path: str,
        methods: List[HTTPMethod],
        endpoint_metadata: ParsedEndpointMetadata,
        responses: Dict[
            int,     
            type[HTML]
            | type[FileUpload]
            | type[Body]
            | type[BaseModel]
            | type[dict]
            | type[list]
            | type[str]
            | type[bytes]
            | str
            | bytes
        ],
        response_headers: Dict[str, Any] | None = None,
        headers: type[Headers] | None = None,
        parameters: type[Parameters] | None = None,
        query: type[Query] | None = None,
        body: (
            type[HTML]
            | type[FileUpload]
            | type[Body]
            | type[BaseModel]
            | type[dict]
            | type[list]
            | type[str]
            | type[bytes]
            | str
            | bytes
            | None
        ) = None,
        required: List[
            Literal[
                "parameters",
                "headers",
                "query",
                "body",
            ]
        ] | None = None,
        default_tags: List[ParsedTag] | None = None
    ) -> None:
        
        if default_tags is None:
            default_tags = []

        if required is None:
            required = []

        self.path = path
        self.path_params: Set[str] = set(re.findall("{(.*?)}", path))
        self.methods = methods
        self.headers = headers
        self.parameters = parameters
        self.query = query
        self.body = body
        self.responses = responses
        self.metadata = endpoint_metadata
        self.required = required
        self.response_headers = response_headers
        self.default_tags = default_tags

        self.parsed_params: List[Parameter] = []
        self._content_type: str | None = None

        self.request_components: Dict[str, Any] = {}
        self.response_components: Dict[str, Any] = {}

    def parse(self) -> PathItem:
        param_types: List[ParamType] = [
            param_type for param_type in [
                self.parameters,
                self.query,
                self.headers
            ] if param_type is not None
        ]

        for param in param_types:
            self.parsed_params.extend(
                parse_param(param, self.path_params)
            )

        operations: Dict[HTTPMethod, Operation] = {}

        for method in self.methods:

            operation_metadata: ParsedOperationMetadata = self.metadata.operations[method]

            operation_tags: List[str] = []

            for tag in self.default_tags:
                if tag.value == operation_metadata.group_name:
                    operation_tags.append(tag.value)

            if operation_metadata.tags:
                operation_tags.extend(operation_metadata.tags)

            operations[method.lower()] = {
                "tags": operation_tags,
                "summary": operation_metadata.summary,
                "description": operation_metadata.description,
                "externalDocs": {
                    "description": operation_metadata.docs_description,
                    "url": operation_metadata.docs_url,
                } if operation_metadata.docs_url else None,
                "operationId": operation_metadata.name,
                "requestBody": self._parse_request_body(),
                "responses": self._parse_response(),
                "deprecated": operation_metadata.deprecated,
            }

        return {
            "description": self.metadata.description,
            "summary": self.metadata.summary,
            "parameters": self.parsed_params,
            **operations
        }

    def _parse_request_body(self) -> RequestBody:

        if self.body is None:
            return None
        
        content_type: str | None = None
        if self._content_type:
            content_type = self._content_type

        required = "body" in self.required
        
        if self.body == FileUpload or self.body in FileUpload.__subclasses__():

            if content_type is None:
                content_type = "application/octet-stream"

            body_config = self.body.model_fields
            body_content_type = body_config.get('content_type')
            body_encoding = body_config.get('encoding')

            if body_content_type and body_content_type.default:
                content_type = body_content_type.default

            encoding: str | None = None
            if body_encoding:
                encoding = body_encoding.default

            return {
                "description": self.body.__doc__,
                "content": {
                    content_type: {
                        "schema": {
                            "type": "string",
                            "format": "file",
                            "contentMediaType": content_type,
                            "contentEncoding": encoding,
                            "examples": self.body.model_json_schema(
                                ref_template=REF_TEMPLATE
                            ).get("examples")
                        },
                    }
                },
                "required": required,
            }

        elif self.body == HTML or self.body in HTML.__subclasses__():

            if content_type is None:
                content_type = "text/html"

            return {
                "description": self.body.__doc__,
                "content": {
                    content_type: {
                        "schema": {
                            "type": "string",
                            "format": "html",
                            "contentMediaType": "text/html",
                            "contentEncoding": "utf-8",
                            "examples": self.body.model_json_schema(
                                ref_template=REF_TEMPLATE
                            ).get("examples")
                        },
                    }
                }
            }

        elif self.body == Body or self.body in Body.__subclasses__():
            content_type = 'application/octet-stream'
        
        elif self.body in BaseModel.__subclasses__() or self.body in RootModel.__subclasses__():

            body_schema = self.body.model_json_schema(ref_template=REF_TEMPLATE)

            if content_type is None:
                content_type = "application/json"
            
            if defs := body_schema.get('$defs'):
                self.request_components.update(defs)
                
                del body_schema['$defs']

            return {
                "description": self.body.__doc__,
                "content": {
                    content_type: {
                        "schema": {
                            **body_schema,
                            "contentMediaType": "application/json",
                            "contentEncoding": "utf-8",
                        },
                    }
                }
            }
        
        elif self.body == str or isinstance(self.body, str):
            content_type = 'text/plain'

        elif self.body == bytes or isinstance(self.body, bytes):
            content_type = 'application/octet-stream'

        elif self.body == dict or self.body == list:
            content_type = 'application/json'

        elif self.body in dict.__subclasses__():
            content_type = 'application/json'
        
        schema_type: SchemaType = "string"
        schema_format: str | None = None
        content_encoding: str | None = None

        match content_type:

            case 'text/plain':
                schema_format = 'string'

            case 'application/octet-stream':
                schema_format = 'binary'

            case 'application/json':
                schema_format = 'json'
                content_encoding = 'utf-8'
        
        examples: List[str] = []
        if isinstance(self.body, str):
            examples.append(self.body)

        elif isinstance(self.body, bytes):
            examples.append(self.body.decode())

        return {
            "description": self.body.__doc__,
            "content": {
                content_type: {
                    "schema": {
                        "type": schema_type,
                        "format": schema_format,
                        "contentMediaType": content_type,
                        "contentEncoding": content_encoding,
                        "examples": examples,
                    },
                }
            }
        }
    
    def _parse_response(self) -> Dict[str, Response]:
        parsed_response_headers = {
            header_name: {
                "description": f'{header_name} header',
                "example": value,
                "required": True,
                "schema": {
                    "type": parse_response_header_type(value),
                },
            } for header_name, value in self.response_headers.items() if header_name.lower() not in [
                'content-type'
            ]
        }

        responses: Dict[int, Dict[str, MediaType]] = {}
        for status_code, response in self.responses.items():
            responses[status_code] = self._parse_response_content(response)

        if self.responses.get(500) is None:
            self.responses[500] = InternalErrorSet
        
        if (
            responses.get(
                500, {}
            ).get('application/json') is None
        ):
            responses[500] = self._parse_response_content(InternalErrorSet)

        if self.responses.get(422) is None:
            self.responses[422] = ValidationErrorGroup
        
        if (
            responses.get(
                422, {}
            ).get('application/json') is None
        ):
            responses[422] = self._parse_response_content(ValidationErrorGroup)


        return {
            str(status_code): {
                "description": parse_response_description(response, status_code),
                "headers": parsed_response_headers,
                "content": responses[status_code],
            } for status_code, response in self.responses.items()
        }
    
    def _parse_response_content(
        self,
        response: (
            type[HTML]
            | type[FileUpload]
            | type[Body]
            | type[BaseModel]
            | type[dict]
            | type[list]
            | type[str]
            | type[bytes]
            | str
            | bytes
        )
    ) -> Dict[str, MediaType]:
    
        content_type: str | None = None
        if self._content_type:
            content_type = self._content_type
        
        if response == FileUpload or response in FileUpload.__subclasses__():

            if content_type is None:
                content_type = "application/octet-stream"

            response_config = response.model_fields
            response_content_type = response_config.get('content_type')
            response_encoding = response_config.get('encoding')

            if response_content_type and response_content_type.default:
                content_type = response_content_type.default

            encoding: str | None = None
            if response_encoding:
                encoding = response_encoding.default

            return {
                    content_type: {
                        "schema": {
                            "type": "string",
                            "format": "file",
                            "contentMediaType": content_type,
                            "contentEncoding": encoding,
                        },
                    },
                }
        
        elif response == HTML or response in HTML.__subclasses__():
            
            if content_type is None:
                content_type = "text/html"

            return {
                content_type: {
                    "schema": {
                        "type": "string",
                        "format": "html",
                        "contentMediaType": "text/html",
                        "contentEncoding": "utf-8",
                        "examples": response.model_json_schema(
                            ref_template=REF_TEMPLATE,
                        ).get("examples")
                    },
                }
            }
        
        elif response == Body or response in Body.__subclasses__():
            content_type = 'application/octet-stream'
        
        elif response in BaseModel.__subclasses__() or response in RootModel.__subclasses__():

            response_schema = response.model_json_schema(ref_template=REF_TEMPLATE)

            if content_type is None:
                content_type = "application/json"

            if defs := response_schema.get('$defs'):
                self.response_components.update(defs)
                del response_schema['$defs']

            return {
                "application/json": {
                    "schema": {
                        **response_schema,
                        "contentMediaType": "application/json",
                        "contentEncoding": "utf-8",
                    },
                }
            }

        elif response == str or isinstance(response, str):
            content_type = 'text/plain'

        elif response == bytes or isinstance(response, bytes):
            content_type = 'application/octet-stream'

        elif response == dict or response == list:
            content_type = 'application/json'

        elif response in dict.__subclasses__():
            content_type = 'application/json'
  
        schema_type: SchemaType = "string"
        schema_format: str | None = None
        content_encoding: str | None = None

        match content_type:

            case 'text/plain':
                schema_format = 'string'

            case 'application/octet-stream':
                schema_format = 'binary'

            case 'application/json':
                schema_format = 'json'
                content_encoding = 'utf-8'

        examples: List[str] = []
        if isinstance(response, str):
            examples.append(response)

        elif isinstance(response, bytes):
            examples.append(response.decode())


        return {
            content_type: {
                "schema": {
                    "type": schema_type,
                    "format": schema_format,
                    "contentMediaType": content_type,
                    "contentEncoding": content_encoding,
                    "examples": examples,
                }
            }
        }

