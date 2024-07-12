from typing import List

from pydantic import BaseModel

from .models import Schema
from .parsed_types import (
    FieldMetadata,
    FieldType,
)


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


def parse_model(model: type[BaseModel]):
    return  Schema(**model.model_json_schema())