from __future__ import annotations
import msgspec
import orjson
from typing import TypeVar


T = TypeVar("T", bound=dict)


class Model(msgspec.Struct):
    @classmethod
    def model_json_schema(cls, ref_template: str | None = None):
        """Return the JSON Schema for ``cls`` suitable for OpenAPI emission.

        When ``ref_template`` is supplied (with the ``{name}`` placeholder
        per msgspec convention), nested-model ``$ref`` values are
        substituted per nested type rather than collapsed to the outer
        class name.

        Pre-fix the implementation pre-substituted ``{model}`` to
        ``cls.__name__`` BEFORE handing the template to msgspec, leaving
        msgspec with no placeholder. Every nested ``$ref`` then collapsed
        to the outer class name and emitted OpenAPI documents were
        unparseable by Swagger UI / ReDoc / openapi-generator.
        """
        if ref_template:
            schemas, defs = msgspec.json.schema_components(
                [cls],
                ref_template=ref_template,
            )

            # ``defs`` is the dict of all named types referenced by the
            # input set (including ``cls`` itself). Pull out cls's own
            # schema and re-attach the remaining defs under ``$defs`` so
            # the docs pipeline can hoist them into ``components/schemas``.
            own = dict(defs.pop(cls.__name__, schemas[0] if schemas else {}))
            if defs:
                own["$defs"] = defs
            return own

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

    @classmethod
    def model_spec(cls):
        return {field.name: field.type for field in msgspec.structs.fields(cls)}

    def model_dump(self, exclude_none: bool = False):
        if exclude_none:
            return {
                key: value.model_dump() if isinstance(value, Model) else value
                for key, value in msgspec.structs.asdict(self).items()
                if value is not None
            }

        return {
            key: value.model_dump() if isinstance(value, Model) else value
            for key, value in msgspec.structs.asdict(self).items()
        }

    def model_dump_json(self, exclude_none: bool = False):
        if exclude_none:
            return orjson.dumps(
                {
                    key: value.model_dump() if isinstance(value, Model) else value
                    for key, value in msgspec.structs.asdict(self).items()
                    if value is not None
                }
            )

        return orjson.dumps(
            {
                key: value.model_dump() if isinstance(value, Model) else value
                for key, value in msgspec.structs.asdict(self).items()
            }
        )

    def model_copy(self, update: T):
        model_dict = msgspec.structs.asdict(self)
        model_dict.update(update)

        return type(self)(**model_dict)
