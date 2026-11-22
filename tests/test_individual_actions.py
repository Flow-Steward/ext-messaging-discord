"""Exercise the dedicated workflow action for every Discord route."""

import json
from pathlib import Path

import pytest

import main
from runtime import rest
from runtime.input_schema import accepts
from test_rest_action import ROUTES, sample_invocation

ROOT = Path(__file__).resolve().parents[1]
ACTIONS = json.loads((ROOT / "runtime/rest_actions.json").read_text())


def sample_value(schema):
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    for union in ("anyOf", "oneOf"):
        if union in schema:
            for branch in schema[union]:
                candidate = sample_value(branch)
                if accepts(candidate, schema):
                    return candidate
    if "allOf" in schema:
        values = [sample_value(branch) for branch in schema["allOf"]]
        if all(isinstance(value, dict) for value in values):
            return {k: v for value in values for k, v in value.items()}
    kind = schema.get("type", "object")
    if isinstance(kind, list):
        kind = next((value for value in kind if value != "null"), "null")
    if kind == "object":
        return {
            field: sample_value(schema["properties"][field]) for field in schema.get("required", [])
        }
    if kind == "array":
        return [sample_value(schema.get("items", {})) for _ in range(schema.get("minItems", 0))]
    if kind == "boolean":
        return True
    if kind in {"integer", "number"}:
        return schema.get("minimum", min(1, schema.get("maximum", 1)))
    if kind == "null":
        return None
    return "1" * max(1, schema.get("minLength", 1))


def independent_invocation(action_id):
    record = ACTIONS[action_id]
    operation = record["operation_id"]
    request, write = sample_invocation(operation, ROUTES[operation])
    action = request["action"]
    action["action_id"] = action_id
    generic = action["input"]
    fields = {"connection_ref": generic["connection_ref"]}
    for contract in record["fields"]:
        field = contract["name"]
        if contract["required"] or (field == "body" and "body" in generic):
            schema = contract["schema"]
            fields[field] = sample_value(schema)
            assert accepts(fields[field], schema), (action_id, field, fields[field])
    for group, bindings in record["bindings"].items():
        generic[group] = {
            parameter: fields[field] for field, parameter in bindings.items() if field in fields
        }
    action["input"] = fields
    return request, write, generic


@pytest.mark.parametrize("action_id", sorted(ACTIONS))
def test_action_executes_only_its_registered_route(monkeypatch, action_id):
    record = ACTIONS[action_id]
    route = ROUTES[record["operation_id"]]
    request, write, generic = independent_invocation(action_id)
    calls = []

    def send(**kwargs):
        calls.append(kwargs)
        status = kwargs["success_statuses"][0]
        return status, "application/json", b"{}" if status != 204 else b""

    monkeypatch.setattr(rest, "request_raw", send)
    result = main.dispatch(request)
    assert result["ok"] is True, result
    [call] = calls
    assert call["method"] == route["method"]
    assert call["path"] == route["path"].format(
        **generic["path_parameters"],
        **{name: "example.route.secret" for name in route["secret_path_parameters"]},
    )
    assert call["success_statuses"] == tuple(route["success_statuses"])
    assert ("external_effect_status" in result) == write
    request["action"]["input"]["operation_id"] = "delete_guild"
    assert main.dispatch(request)["error_code"] == "invalid_payload"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "action_id", sorted(key for key, value in ACTIONS.items() if value["write"])
)
def test_dedicated_write_actions_are_suppressed(monkeypatch, action_id):
    def unexpected(**kwargs):
        pytest.fail("Dry run called Discord")

    monkeypatch.setattr(rest, "request_raw", unexpected)
    request, _, _ = independent_invocation(action_id)
    request["runtime_context"]["test_mode"] = True
    assert main.dispatch(request) == {"ok": True, "result": {"response": {}, "suppressed": True}}


def test_exactly_250_dedicated_actions_have_forms_and_contracts():
    import yaml

    contracts = yaml.safe_load((ROOT / "contracts/operation_manifest.yaml").read_text())
    forms = yaml.safe_load((ROOT / "contracts/step_ui_manifest.yaml").read_text())
    manifests = yaml.safe_load((ROOT / "ui/actions/actions.yaml").read_text())
    assert {entry["operation_id"] for entry in ACTIONS.values()} == set(ROUTES)
    assert len(ACTIONS) == 250
    assert {
        item["operation_id"]
        for item in contracts["operations"]
        if item["operation_id"].startswith("rest_")
    } == set(ACTIONS)
    assert {
        item["operation_id"] for item in forms["forms"] if item["operation_id"].startswith("rest_")
    } == set(ACTIONS)
    assert {
        item["action_id"] for item in manifests["actions"] if item["action_id"].startswith("rest_")
    } == set(ACTIONS)


def test_generated_contracts_are_current():
    from subprocess import run
    from sys import executable

    run([executable, str(ROOT / "scripts/build_actions.py"), "--check"], check=True)
