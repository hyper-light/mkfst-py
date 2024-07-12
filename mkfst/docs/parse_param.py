from typing import List, Set

from mkfst.models.http import Headers, Parameters, Query

from .models import Parameter
from .parsed_types import FieldMetadata, FieldsMetadata, FieldType, PropertyMetadata


def parse_type(field: FieldMetadata) -> List[str] | str:
    field_data: List[FieldType] = field.get("anyOf")
    if field_data:
        return {
            'enum': [
                field_type.get("type") for field_type in field_data
            ]
        }
    
    return {
        'type': field.get("type", "string")
    }


def format_header_name(name: str):
    return '-'.join([
        segment.capitalize() for segment in name.split('_')
    ])

def parse_param(
    param: type[Headers] | type[Parameters] | type[Query],
    path_params: Set[str]
) -> Parameter:

    schema: PropertyMetadata = param.model_json_schema()
    metadata: FieldsMetadata = schema.get('properties')
    required = schema.get('required', [])

    fields = list(param.model_fields.keys())

    if param == Parameters:
        fields = [
            field for field in fields if field in path_params
        ]

        additional_params = list(filter(
            lambda path_param: path_param not in fields,
            path_params
        ))

        for path_param in additional_params:
            metadata[path_param] = {
                "type": "string",
                "format": "string",
            }

            fields.append(path_param)

    location: str | None = None

    if param == Headers or param in Headers.__subclasses__():
        location = 'header'

    elif param == Query or param in Query.__subclasses__():
        location = 'query'

    elif param == Parameters or param in Parameters.__subclasses__():
        location = 'path'

    else:
        location = 'cookie'

    return [
        {
            'name': format_header_name(
                field
            ) if location == 'header' else field,
            'description': f'{field} header',
            'required': field in required,
            'in': location,
            'schema': {
                **parse_type(
                    metadata.get(field)
                ),
                'format': metadata.get(
                    field, {}
                ).get('format')
            }
        } for field in fields
    ]