import datetime
import uuid
from typing import List, get_args, get_type_hints

from mkfst.docs.parsed_types import (
    FieldMetadata,
    FieldsMetadata,
    FieldType,
    PropertyMetadata,
)
from pydantic import (
    AnyHttpUrl,
    BaseModel,
    EmailStr,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    conlist,
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

    schema: PropertyMetadata = model.model_json_schema()
    metadata: FieldsMetadata = schema.get('properties')

    required: List[str] = schema.get('required')

    fields = model.model_fields

    return  {
        "title": model.__name__,
        "type": "string",
        "format": "json",
        "contentMediaType": 'application/json',
        "contentEncoding": 'utf-8',
        "properites": {
            field: {
                **metadata[field],
                **parse_type(metadata[field])


            }for field in fields 
        },
        "required": required
    }


class Test(BaseModel):
    boop: StrictInt


class ExampleItem(BaseModel):
    email: EmailStr
    date: datetime.datetime
    test: Test


class ExampleResponse(BaseModel):
    response_id: uuid.UUID = Field(description='Response ID field')
    url: AnyHttpUrl
    message: StrictStr | StrictInt = 'Hello'
    data: conlist(ExampleItem, min_length=0)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "response_id": uuid.uuid4(),
                    "url": "https://httpbin.org/get",
                    "message": "Hello",
                    "data": [
                        {
                            "email": "eee@eee.eee",
                            "date": datetime.datetime.now().isoformat()
                        }
                    ]
                }
            ]
    }
    }


try:
    ex = ExampleResponse(**{
        "test": "this"
    })

except ValidationError as e:
    print(e.json())


def test_inspect() -> tuple[str, int]:
    pass


return_annotation = get_type_hints(test_inspect).get('return')
return_args = get_args(return_annotation)

if len(return_args) > 0 and isinstance(return_annotation(), tuple):
    return_type = return_args[0]

print(return_type, return_args)


print(isinstance(return_type, tuple))
print(tuple.__name__)