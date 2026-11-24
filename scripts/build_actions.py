"""Generate individual Flow Steward actions from the pinned Discord specification."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

import yaml
from build_rest_registry import ROOT, build_routes, load_spec
from step_docs import describe, field_doc

sys.path.insert(0, str(ROOT))
from runtime.paging import PAGING  # noqa: E402

PREFIX = "rest_"
MARKER = "# Generated Discord REST actions. Run scripts/build_actions.py."
ERRORS = [
    "invalid_payload",
    "invalid_connection",
    "upstream_validation_failed",
    "authentication_failed",
    "access_denied",
    "not_found",
    "rate_limited",
    "provider_unavailable",
]
KINDS = {
    "string": ("text", "string", "text"),
    "integer": ("integer", "integer", "number"),
    "number": ("number", "number", "number"),
    "boolean": ("boolean", "boolean", "boolean"),
    "array": ("array", "array", "json"),
    "object": ("object", "object", "json"),
}
SCALAR_KEYS = {
    "type",
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "pattern",
    "enum",
    "const",
    "minItems",
    "maxItems",
}
BODY_CREDENTIALS = {"access_token", "secret", "client_secret", "external_auth_token"}
READ_ERRORS = ["invalid_response", "response_too_large"]
#: The per-file grant for a workflow file: Discord's default upload limit, 20 MiB per file
#: (discord-api-docs 9b737ec, developers/reference.mdx, "Uploading Files").
MAX_FILE_BYTES = 20 * 1024 * 1024
FILE_BINDING = "discord_file"
COMMON_OUTPUTS = [
    {"name": "response", "value_type": "object", "schema": {"type": "object"}},
    {"name": "suppressed", "value_type": "boolean", "schema": {"type": "boolean"}},
    {"name": "rate_limit", "value_type": "object", "schema": {"type": "object"}},
    {
        "name": "warnings",
        "value_type": "array",
        "schema": {"type": "array", "items": {"type": "string"}},
    },
]
WRITE_OUTPUTS = [{"name": "processing", "value_type": "text", "schema": {"type": "string"}}]
PAGING_OUTPUTS = [
    {"name": "next_cursor", "value_type": "text", "schema": {"type": "string"}},
    {"name": "complete", "value_type": "boolean", "schema": {"type": "boolean"}},
    {"name": "pages", "value_type": "integer", "schema": {"type": "integer"}},
]
FILE_ARTIFACTS_SCHEMA = {
    "type": "array",
    "maxItems": 10,
    "items": {
        "type": "object",
        "required": ["field", "filename", "artifact_handle"],
        "properties": {key: {"type": "string"} for key in ("field", "filename", "artifact_handle")},
        "additionalProperties": False,
    },
}


def project(schema: dict[str, Any], definitions: dict[str, Any], depth: int = 3) -> dict[str, Any]:
    """Inline a bounded, executable subset of the upstream schema."""
    ref = schema.get("$ref")
    if ref:
        return project(definitions[ref.rsplit("/", 1)[-1]], definitions, depth)
    result = {key: value for key, value in schema.items() if key in SCALAR_KEYS}
    if depth < 0:
        return {key: value for key, value in result.items() if key in {"type", "enum", "const"}}
    for key in ("items", "additionalProperties"):
        value = schema.get(key)
        if isinstance(value, dict):
            result[key] = project(value, definitions, depth - 1)
        elif isinstance(value, bool) and key == "additionalProperties":
            result[key] = value
    if "properties" in schema:
        result["properties"] = {
            key: project(value, definitions, depth - 1)
            for key, value in schema["properties"].items()
        }
    if schema.get("required"):
        result["required"] = schema["required"]
    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema:
            result[key] = [project(value, definitions, depth - 1) for value in schema[key]]
    return result


def public_body_schema(schema: dict[str, Any]) -> dict[str, Any]:
    result = dict(schema)
    if "properties" in result:
        omitted = BODY_CREDENTIALS | {
            name
            for name in result["properties"]
            if name == "file" or name.startswith("files[") or name.endswith("_file")
        }
        result["properties"] = {
            key: value for key, value in result["properties"].items() if key not in omitted
        }
        if "required" in result:
            result["required"] = [key for key in result["required"] if key not in omitted]
        for key in sorted(omitted.intersection(schema["properties"])):
            result["properties"][key] = {"not": {}}
    for union in ("anyOf", "oneOf", "allOf"):
        if union in result:
            result[union] = [public_body_schema(item) for item in result[union]]
    return result


def make_field(
    name: str,
    schema: dict[str, Any],
    required: bool,
    help_text: str = "",
    *,
    label: str = "",
) -> dict:
    kind = schema.get("type")
    value_type, parameter_type, widget = KINDS.get(
        kind if isinstance(kind, str) else "", KINDS["object"]
    )
    ui = {
        "name": name,
        "label": label or name.replace("_", " ").capitalize(),
        "widget_type": widget,
        "required": required,
    }
    if help_text:
        ui["help_text"] = help_text
    return {
        "contract": {
            "name": name,
            "value_type": value_type,
            "required": required,
            "schema": schema,
        },
        "parameter": {"name": name, "type": parameter_type, "required": required},
        "ui": ui,
    }


def connection_types(route: dict[str, Any]) -> list[str]:
    if route["secret_path_parameters"]:
        return ["discord_route_token"]
    return [
        connection
        for auth, connection in (("BotToken", "discord_bot"), ("OAuth2", "discord_oauth_token"))
        if any(auth in alternative for alternative in route["security"])
    ]


def generated(spec: dict[str, Any]) -> tuple[dict[str, list[dict]], dict[str, dict]]:
    manifests: dict[str, list[dict]] = {
        "contracts/operation_manifest.yaml": [],
        "ui/actions/actions.yaml": [],
        "contracts/step_ui_manifest.yaml": [],
        "extension.yaml": [],
        "contracts/artifact_policies.yaml": [],
    }
    runtime: dict[str, dict] = {}
    definitions = spec["components"]["schemas"]
    for operation_id, route in sorted(build_routes(spec).items()):
        action_id = PREFIX + operation_id
        method, path = route["method"], route["path"]
        item = spec["paths"][path]
        operation = item[method.lower()]
        write = method not in {"GET", "HEAD", "OPTIONS"}
        title, summary, _page = describe(operation_id, method, path)

        def documented(
            name: str, schema: dict[str, Any], required: bool, location: str = ""
        ) -> dict:
            label, text = field_doc(name, location, method, path)
            return make_field(name, schema, required, text, label=label)

        fields = []
        bindings: dict[str, dict[str, str]] = {"path_parameters": {}, "query_parameters": {}}
        parameters = {
            (p["in"], p["name"]): p
            for p in [*item.get("parameters", []), *operation.get("parameters", [])]
        }
        repeated = set(route["path_parameters"]) & set(route["query_parameters"])
        for location, names in (
            ("path", route["path_parameters"]),
            ("query", route["query_parameters"]),
        ):
            for name in names:
                if location == "path" and name in route["secret_path_parameters"]:
                    continue
                parameter = parameters[location, name]
                schema = project(parameter["schema"], definitions)
                field_name = (
                    f"{location}_{name}"
                    if name in repeated
                    or name in {"body", "connection_ref", "files", "media_type", "audit_reason"}
                    else name
                )
                fields.append(
                    documented(field_name, schema, bool(parameter.get("required")), location)
                )
                bindings[f"{location}_parameters"][field_name] = name

        media = route["request_media_types"]
        if media:
            body_schemas = {
                kind: project(
                    content["schema"],
                    definitions,
                    8 if operation_id == "update_application_identity_profile" else 2,
                )
                for kind, content in operation["requestBody"]["content"].items()
            }
            candidates = []
            for candidate in body_schemas.values():
                public = public_body_schema(candidate)
                if public not in candidates:
                    candidates.append(public)
            public_body = candidates[0] if len(candidates) == 1 else {"anyOf": candidates}
            fields.append(
                documented(
                    "body",
                    {
                        "type": "object",
                        "properties": {"data": public_body},
                        "required": ["data"],
                        "additionalProperties": False,
                    },
                    route["request_body_required"] and "multipart/form-data" not in media,
                )
            )
            if len(media) > 1:
                field = documented("media_type", {"type": "string", "enum": media}, False)
                field["ui"].update(
                    widget_type="select", options=[{"value": m, "label": m} for m in media]
                )
                fields.append(field)
            if "multipart/form-data" in media:
                artifacts = documented(
                    "file_artifacts", copy.deepcopy(FILE_ARTIFACTS_SCHEMA), False
                )
                fields.append(
                    documented(
                        "files",
                        {
                            "type": "array",
                            "maxItems": 10,
                            "items": {
                                "type": "object",
                                "required": ["field", "filename", "data_base64"],
                                "properties": {
                                    key: {"type": "string"}
                                    for key in ("field", "filename", "data_base64")
                                },
                                "additionalProperties": False,
                            },
                        },
                        False,
                    )
                )
                fields.append(artifacts)
        paging = None if write else PAGING.get(operation_id)
        if paging is not None:
            fields.append(documented("all_pages", {"type": "boolean"}, False))
        if write:
            fields.append(documented("audit_reason", {"type": "string", "maxLength": 512}, False))
        types = connection_types(route)
        if not types:
            raise ValueError(f"No usable connection type for {operation_id}")
        errors = ERRORS + (["timeout_unknown"] if write else READ_ERRORS)
        if route.get("provider_disabled"):
            errors = [*errors, "operation_disabled"]
        description = f"{summary} Discord: {method} {path}."
        if paging is not None:
            first = paging.directions[0]
            description += (
                f" With all_pages it reads every page ({first} the step's cursor, or from "
                f"the {'first' if first == 'after' else 'newest'} item without one) and "
                f"returns next_cursor to pass as {first} when the list did not end."
            )
        outputs = copy.deepcopy(
            [
                *COMMON_OUTPUTS,
                *(WRITE_OUTPUTS if write else []),
                *(PAGING_OUTPUTS if paging is not None else []),
            ]
        )
        contract = {
            "operation_id": action_id,
            "display_name": title,
            "description": description,
            "operation_kind": "action" if write else "source",
            "category": "messaging",
            "connection_type_ids": types,
            "workflow_visible": True,
            "inputs": [
                {"name": "connection_ref", "value_type": "connection_ref", "required": True},
                *[f["contract"] for f in fields],
            ],
            "outputs": outputs,
            "result_fields": [f"result.{output['name']}" for output in outputs],
            "error_codes": errors,
        }
        action = {
            "action_id": action_id,
            "title": title,
            "description": description,
            "required_scopes": ["extension:invoke"],
            "handler": {"mode": "extension"},
            "mutates_platform": write,
            "workflow_visible": True,
            "parameters": [
                {"name": "connection_ref", "type": "connection_ref", "required": True},
                *[f["parameter"] for f in fields],
            ],
            "result_fields": [output["name"] for output in outputs],
            "error_codes": errors,
        }
        if write:
            effect = f"discord_{operation_id}"
            contract["effect_kind"] = effect
            action["command_type"] = "invoke_extension_action"
            manifests["extension.yaml"].append(
                {
                    "operation_id": action_id,
                    "effect_kind": effect,
                    "channel": "discord_rest_api",
                    "idempotency": "required",
                    "test_mode_behavior": "suppress",
                }
            )
        if "multipart/form-data" in media:
            manifests["contracts/artifact_policies.yaml"].append(
                {
                    "operation_id": action_id,
                    "inputs": [
                        {
                            "kind": "artifact",
                            "value_type": "artifact_handle",
                            "binding_key": FILE_BINDING,
                            "field": "file_artifacts",
                            "required": False,
                            "max_size_bytes": MAX_FILE_BYTES,
                        }
                    ],
                }
            )
        manifests["contracts/operation_manifest.yaml"].append(contract)
        manifests["ui/actions/actions.yaml"].append(action)
        manifests["contracts/step_ui_manifest.yaml"].append(
            {
                "operation_id": action_id,
                "title": title,
                "fields": [f["ui"] for f in fields],
            }
        )
        runtime[action_id] = {
            "operation_id": operation_id,
            "write": write,
            "bindings": bindings,
            "fields": [f["contract"] for f in fields],
        }
    return manifests, runtime


#: The hand-written steps and the Discord route whose documentation describes their inputs.
HAND_STEP_ROUTES = {
    "send_message": ("POST", "/channels/{channel_id}/messages"),
    "get_channel": ("GET", "/channels/{channel_id}"),
    "list_messages": ("GET", "/channels/{channel_id}/messages"),
    "get_guild": ("GET", "/guilds/{guild_id}"),
    "list_guild_channels": ("GET", "/guilds/{guild_id}/channels"),
    "discord_rest_read": ("GET", "/"),
    "discord_rest_write": ("POST", "/"),
}


def documented_head(head: str) -> str:
    """The hand-written forms above the marker, each input labelled and described like
    the same input of the generated steps."""
    data = yaml.safe_load(head) or {}
    for form in data.get("forms", []):
        method, path = HAND_STEP_ROUTES.get(form["operation_id"], ("GET", "/"))
        for field in form.get("fields", []):
            location = "path" if field["name"].endswith("_id") else "query"
            field["label"], field["help_text"] = field_doc(field["name"], location, method, path)
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)


def render(path: Path, records: list[dict]) -> str:
    original = path.read_text()
    body = original.split(MARKER, 1)[0]
    if path.name == "step_ui_manifest.yaml":
        body = documented_head(body)
    indent = "" if path.name == "step_ui_manifest.yaml" else "  "
    block = (
        MARKER
        + "\n"
        + "".join(
            indent + line + "\n"
            for line in yaml.safe_dump(records, sort_keys=False, allow_unicode=True).splitlines()
        )
    )
    if path.name == "extension.yaml":
        before, runtime = original.split("\nruntime:\n", 1)
        return before.split(MARKER, 1)[0].rstrip() + "\n" + block + "runtime:\n" + runtime
    return body.rstrip() + "\n" + block


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    manifests, runtime = generated(load_spec())
    files = {ROOT / name: render(ROOT / name, rows) for name, rows in manifests.items()}
    files[ROOT / "runtime/rest_actions.json"] = (
        json.dumps(runtime, sort_keys=True, separators=(",", ":")) + "\n"
    )
    for path, expected in files.items():
        if args.check:
            if path.read_text() != expected:
                raise SystemExit(f"{path.name} is out of date")
        else:
            path.write_text(expected)


if __name__ == "__main__":
    main()
