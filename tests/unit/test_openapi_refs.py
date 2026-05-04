"""Regression tests for the OpenAPI ``$ref`` substitution.

Pre-fix ``Model.model_json_schema(ref_template=...)`` substituted
``{model}`` to the outer class up front. msgspec then received a
template with no placeholder, so every nested ``$ref`` collapsed to the
outer class name. Generated OpenAPI documents were unparseable by
Swagger UI / ReDoc / openapi-generator."""

from __future__ import annotations

from mkfst.docs.endpoint_parser import REF_TEMPLATE
from mkfst.models.http import Model


class _Inner(Model):
    x: int
    label: str


class _Outer(Model):
    inner: _Inner
    name: str


def test_ref_template_uses_msgspec_name_placeholder() -> None:
    """The template must contain the literal ``{name}`` placeholder so
    msgspec can substitute per nested type rather than us collapsing it
    up front."""
    assert "{name}" in REF_TEMPLATE


def test_nested_refs_resolve_to_correct_named_components() -> None:
    schema = _Outer.model_json_schema(ref_template=REF_TEMPLATE)
    # The outer class's own properties.
    properties = schema["properties"]
    # Nested ref must resolve to the *Inner* component, not the outer.
    inner_ref = properties["inner"]["$ref"]
    assert inner_ref == "#/components/schemas/_Inner"
    # Nested defs are attached under "$defs" for the docs pipeline to
    # promote into the OpenAPI components/schemas section.
    defs = schema["$defs"]
    assert "_Inner" in defs
    assert defs["_Inner"]["properties"]["x"]["type"] == "integer"


def test_no_ref_template_falls_back_to_inline_schema() -> None:
    """The default no-ref-template path returns the cls schema inline."""
    schema = _Outer.model_json_schema()
    assert schema.get("type") == "object"
    assert "properties" in schema


def test_two_independent_models_do_not_alias_each_other() -> None:
    """Pre-fix the up-front substitution meant calling
    ``model_json_schema`` for two different classes would emit a ``$ref``
    to whichever class was passed in last — i.e. all refs aliased the
    same outer name."""
    a = _Outer.model_json_schema(ref_template=REF_TEMPLATE)
    b = _Inner.model_json_schema(ref_template=REF_TEMPLATE)
    assert a["properties"]["inner"]["$ref"] == "#/components/schemas/_Inner"
    # _Inner has no nested refs of its own.
    assert "$defs" not in b
    assert b["properties"]["x"]["type"] == "integer"
