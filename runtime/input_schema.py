"""Validate the executable schema subset emitted for named Discord actions."""

from __future__ import annotations

import re
from typing import Any

TYPES = {
    "null": lambda value: value is None,
    "string": lambda value: isinstance(value, str),
    "boolean": lambda value: type(value) is bool,
    "integer": lambda value: type(value) is int,
    "number": lambda value: type(value) in {int, float},
    "object": lambda value: isinstance(value, dict),
    "array": lambda value: isinstance(value, list),
}


def _matches_type(value: Any, types: str | list[str] | None) -> bool:
    if types is None:
        return True
    return any(TYPES[name](value) for name in ([types] if isinstance(types, str) else types))


def accepts(value: Any, schema: dict[str, Any]) -> bool:
    if not _matches_type(value, schema.get("type")):
        return False
    if "const" in schema and value != schema["const"]:
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if "not" in schema and accepts(value, schema["not"]):
        return False
    if "allOf" in schema and not all(accepts(value, branch) for branch in schema["allOf"]):
        return False
    if "anyOf" in schema and not any(accepts(value, branch) for branch in schema["anyOf"]):
        return False
    if "oneOf" in schema and sum(accepts(value, branch) for branch in schema["oneOf"]) != 1:
        return False
    if isinstance(value, str):
        return schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", len(value)) and (
            "pattern" not in schema or re.search(schema["pattern"], value) is not None
        )
    if type(value) in {int, float}:
        return schema.get("minimum", value) <= value <= schema.get("maximum", value)
    if isinstance(value, list):
        return schema.get("minItems", 0) <= len(value) <= schema.get(
            "maxItems", len(value)
        ) and all(accepts(item, schema.get("items", {})) for item in value)
    if isinstance(value, dict):
        if not set(schema.get("required", ())).issubset(value):
            return False
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for name, item in value.items():
            field = properties.get(name, additional)
            if field is False or (isinstance(field, dict) and not accepts(item, field)):
                return False
    return True
