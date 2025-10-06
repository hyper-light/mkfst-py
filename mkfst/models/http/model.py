import msgspec
import orjson
from typing import TypeVar


T = TypeVar("T", bound=dict)


class Model(msgspec.Struct):
    @classmethod
    def model_json_schema(cls, ref_template: str | None = None):
        if ref_template:
            components: tuple[dict[str, dict]] = msgspec.json.schema_components(
                [cls],
                ref_template=ref_template.format(model=cls.__name__),
            )

            schema_properties = {}

            for item in components:
                if isinstance(item, dict):
                    schema_properties.update(
                        item.get(
                            "$defs",
                            {},
                        ).get(cls.__name__, {})
                    )

            return schema_properties

        else:
            component: dict[str, dict] = msgspec.json.schema(cls)
            return component.get(
                "$defs",
                {},
            ).get(cls.__name__, {})

    @classmethod
    def defaults(cls):
        return {field.name: field.default for field in msgspec.structs.fields(cls)}

    @classmethod
    def model_fields(cls):
        return {field.name: field for field in msgspec.structs.fields(cls)}

    def model_dump(self, exclude_none: bool = False):
        if exclude_none:
            return {
                key: value
                for key, value in msgspec.structs.asdict(self)
                if value is not None
            }

        return msgspec.structs.asdict(self)

    def model_dump_json(self, exclude_none: bool = False):
        if exclude_none:
            return orjson.dumps(
                {
                    key: value
                    for key, value in msgspec.structs.asdict(self)
                    if value is not None
                }
            )

        return orjson.dumps(msgspec.structs.asdict(self))

    def model_copy(self, update: T):
        model_dict = msgspec.structs.asdict(self)
        model_dict.update(update)

        return type(self)(**model_dict)
