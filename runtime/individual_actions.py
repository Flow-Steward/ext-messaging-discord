"""Bind named action inputs to one fixed Discord endpoint."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runtime.input_schema import accepts
from runtime.rest_action import dispatch_rest, failure

_ACTIONS = json.loads(Path(__file__).with_name("rest_actions.json").read_text())
ENVELOPE_FIELDS = frozenset({"body", "files", "media_type", "audit_reason"})


def dispatch_individual(
    operation: str, action: dict[str, Any], inputs: dict[str, Any], context: Any, *, user_agent: str
) -> dict[str, Any] | None:
    spec = _ACTIONS.get(operation)
    if spec is None:
        return None
    allowed = {field["name"] for field in spec["fields"]}
    if inputs.keys() - allowed - {"connection_ref"}:
        return failure("invalid_payload")
    if any(field["required"] and field["name"] not in inputs for field in spec["fields"]):
        return failure("invalid_payload")
    if any(
        field["name"] in inputs and not accepts(inputs[field["name"]], field["schema"])
        for field in spec["fields"]
    ):
        return failure("invalid_payload")
    normalized = {field: value for field, value in inputs.items() if field in ENVELOPE_FIELDS}
    normalized["connection_ref"] = inputs.get("connection_ref")
    normalized["operation_id"] = spec["operation_id"]
    for group, bindings in spec["bindings"].items():
        normalized[group] = {
            parameter: inputs[field] for field, parameter in bindings.items() if field in inputs
        }
    return dispatch_rest(action, normalized, context, write=spec["write"], user_agent=user_agent)
