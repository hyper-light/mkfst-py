from typing import Any, Dict, List

from .endpoint_parser import EndpointParser
from .models import (
  ServerVariable,
)
from .parsed_api_metadata import ParsedAPIMetadata
from .parsed_api_server import ParsedAPIServer
from .parsed_endpoint import ParsedEndpoint
from .parsed_tag import ParsedTag


def remove_none(obj):
  if isinstance(obj, (list, tuple, set)):
    return type(obj)(remove_none(x) for x in obj if x is not None)
  elif isinstance(obj, dict):
    return type(obj)((remove_none(k), remove_none(v))
      for k, v in obj.items() if k is not None and v is not None)
  else:
    return obj

def create_api_definition(
    api_metadata: ParsedAPIMetadata,
    api_config: ParsedAPIServer,
    endpoints: Dict[str, ParsedEndpoint],
    tags: List[ParsedTag]
):  

    endpoint_parsers = [
        EndpointParser(
            **parsed.to_dict(),
            default_tags=tags
        ) for parsed in endpoints.values()
    ]

    server_variables: Dict[str, ServerVariable] | None = None
    if api_config.server_variables:
        server_variables = {
            name: {
                "enum": variable.options,
                "default": variable.default,
                "description": variable.description,
            } for name, variable in api_config.server_variables.items()
        }
    schema_components: Dict[str, Any] = {}
    paths: Dict[str, Any] = {}
    for parser in endpoint_parsers:
       paths[parser.path] = parser.parse()
       schema_components.update(parser.request_components)
       schema_components.update(parser.response_components)
    
    schema = {
        "openapi": '3.1.0',
        "tags": [
           tag.parse() for tag in tags
        ],
        "info": {
            "title": api_metadata.title,
            "summary": api_metadata.summary,
            "description": api_metadata.description,
            "termsOfService": api_metadata.terms_of_service,
            "contact": {
                "name": api_metadata.owner,
                "url": api_metadata.owner_url.unicode_string() if api_metadata.owner_url else None,
                "email": api_metadata.owner_email
            },
            "license": {
                "name": api_metadata.license,
                "identifier": api_metadata.license_identifier,
                "url": api_metadata.license_url.unicode_string() if api_metadata.license_url else None,
            } if api_metadata.license else None,
            "version": api_metadata.version     
        },
        "servers": [
            {
                "url": api_config.server_url.unicode_string(),
                "description": api_config.server_description,
                "variables": server_variables,
            }
        ],
        "components": {
            "schemas": schema_components
        },
        "paths": {
            parser.path: parser.parse() for parser in endpoint_parsers
        }
    }
  
    return remove_none(schema)

