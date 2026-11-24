"""Exercise the dedicated workflow action for every Discord route."""

import json
from email import policy
from email.parser import BytesParser
from io import BytesIO
from urllib.error import HTTPError
from pathlib import Path

import pytest

import main
from discord_fakes import Response, documented_reply, pinned, reply
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


EXECUTABLE_ACTIONS = sorted(
    key
    for key, record in ACTIONS.items()
    if not ROUTES[record["operation_id"]].get("provider_disabled")
)


@pytest.mark.parametrize("action_id", EXECUTABLE_ACTIONS)
def test_action_executes_only_its_registered_route(monkeypatch, action_id):
    record = ACTIONS[action_id]
    route = ROUTES[record["operation_id"]]
    request, write, generic = independent_invocation(action_id)
    calls = []

    def send(**kwargs):
        calls.append(kwargs)
        status = kwargs["success_statuses"][0]
        return documented_reply(route, status)

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
    from test_rest_action import TEST_RUN

    def unexpected(**kwargs):
        pytest.fail("Dry run called Discord")

    monkeypatch.setattr(rest, "request_raw", unexpected)
    request, _, _ = independent_invocation(action_id)
    request["runtime_context"]["test_mode"] = True
    if ROUTES[ACTIONS[action_id]["operation_id"]].get("provider_disabled"):
        assert main.dispatch(request)["error_code"] == "operation_disabled"
    else:
        assert main.dispatch(request) == TEST_RUN


def test_all_dedicated_actions_have_forms_and_contracts():
    import yaml

    contracts = yaml.safe_load((ROOT / "contracts/operation_manifest.yaml").read_text())
    forms = yaml.safe_load((ROOT / "contracts/step_ui_manifest.yaml").read_text())
    manifests = yaml.safe_load((ROOT / "ui/actions/actions.yaml").read_text())
    assert {entry["operation_id"] for entry in ACTIONS.values()} == set(ROUTES)
    assert len(ACTIONS) == 258
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


def test_discord_disabled_batch_permissions_action_never_calls_upstream(monkeypatch):
    request, _, _ = independent_invocation("rest_batch_edit_application_command_permissions")
    monkeypatch.setattr(
        rest, "request_raw", lambda **_: pytest.fail("Disabled route called Discord")
    )
    result = main.dispatch(request)
    assert result["error_code"] == "operation_disabled"
    assert result["definitely_no_external_effect"] is True


FILE_FIELDS = {
    "create_channel_invite": "target_users_file",
    "create_guild_sticker": "file",
    "upload_application_attachment": "file",
    "update_invite_target_users": "target_users_file",
}


@pytest.mark.parametrize(
    "action_id",
    [
        key
        for key in EXECUTABLE_ACTIONS
        if "multipart/form-data" in ROUTES[ACTIONS[key]["operation_id"]]["request_media_types"]
    ],
)
def test_multipart_upload_delivers_binary_file(monkeypatch, action_id):
    request, _, _ = independent_invocation(action_id)
    operation = ACTIONS[action_id]["operation_id"]
    field = FILE_FIELDS.get(operation, "files[0]")
    mime_types = ROUTES[operation]["request_media_types"]
    inputs = request["action"]["input"]
    if len(mime_types) > 1:
        inputs["media_type"] = "multipart/form-data"
    if operation == "create_guild_sticker":
        inputs["body"] = {"data": {"name": "Fixture", "tags": "example"}}
    filename = "fixture.png" if operation == "create_guild_sticker" else "fixture.bin"
    inputs["files"] = [{"field": field, "filename": filename, "data_base64": "AAEC/w=="}]
    calls = []

    def send(**kwargs):
        calls.append(kwargs)
        return reply(kwargs["success_statuses"][0])

    monkeypatch.setattr(rest, "request_raw", send)
    assert main.dispatch(request)["ok"] is True
    [call] = calls
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {call['content_type']}\r\nMIME-Version: 1.0\r\n\r\n".encode()
        + bytes(call["data"])
    )
    [attachment] = [part for part in message.iter_parts() if part.get_filename()]
    assert attachment.get_param("name", header="content-disposition") == field
    assert attachment.get_filename() == filename
    assert attachment.get_content_type() == (
        "image/png" if operation == "create_guild_sticker" else "application/octet-stream"
    )
    assert attachment.get_payload(decode=True) == b"\x00\x01\x02\xff"
    if operation == "create_guild_sticker":
        assert any(
            part.get_param("name", header="content-disposition") == "name"
            and part.get_payload(decode=True) == b"Fixture"
            for part in message.iter_parts()
        )


WRITES = [key for key in EXECUTABLE_ACTIONS if ACTIONS[key]["write"]]


@pytest.mark.parametrize("action_id", [*WRITES, "send_message"])
@pytest.mark.parametrize("failure_mode", ["timeout", "http_502", "unexpected_status"])
def test_write_is_attempted_once_and_reports_uncertain_outcome(
    monkeypatch, action_id, failure_mode
):
    from test_flowsteward_discord import invocation

    if action_id == "send_message":
        request = invocation(action_id)
        request["action"]["input"].update(channel_id="123", content="Example")
    else:
        request, _, _ = independent_invocation(action_id)
    calls = []

    class UnexpectedResponse:
        status = 299

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def open_pinned(http_request):
        calls.append(http_request)
        if failure_mode == "timeout":
            raise TimeoutError("provider diagnostic with a secret")
        if failure_mode == "http_502":
            raise HTTPError(http_request.full_url, 502, "provider diagnostic", {}, BytesIO(b"{}"))
        return UnexpectedResponse()

    pinned(monkeypatch, open_pinned)
    result = main.dispatch(request)
    assert len(calls) == 1
    assert result["error_code"] == "timeout_unknown"
    assert result["external_effect_status"] == "timeout_unknown"
    assert result["definitely_no_external_effect"] is False
    assert "provider diagnostic" not in repr(result)


@pytest.mark.parametrize(
    "operation",
    [
        "create_webhook",
        "get_webhook",
        "get_webhook_by_token",
        "list_channel_webhooks",
        "get_guild_webhooks",
        "create_interaction_response",
        "bot_partner_sdk_token",
        "partner_sdk_token",
    ],
)
@pytest.mark.parametrize("response_kind", ["success", "error"])
def test_provider_credentials_never_leave_dispatch(
    monkeypatch, caplog, capsys, operation, response_kind
):
    request, _, _ = independent_invocation(f"rest_{operation}")
    result_tokens = {
        "token": "new.fixture.webhook",
        "interactionToken": "new.fixture.interaction",
        "bot_token": "new.fixture.bot",
        "access_token": "new.fixture.oauth",
        "refresh_token": "new.fixture.refresh",
    }
    urls = [
        "https://discord.com/api/v10/webhooks/123/new%2Efixture%2Eurl",
        "https://discord.com/api/v10/interactions/123/new.fixture.interaction/callback",
        "https://discord.com?access_token=new.fixture.query",
    ]
    payload = json.dumps(
        {
            "credentials": [{key: value} for key, value in result_tokens.items()],
            "urls": urls,
            "copied": list(result_tokens.values()) + ["new.fixture.url", "new.fixture.query"],
            "public": {"id": "42"},
            "message": " diagnostic ".join(result_tokens.values()),
        }
    ).encode()

    status = next(status for status in ROUTES[operation]["success_statuses"] if status != 204)

    def open_pinned(http_request):
        if response_kind == "error":
            raise HTTPError(http_request.full_url, 400, str(result_tokens), {}, BytesIO(payload))
        return Response(status, payload, {"Content-Type": "application/json"})

    pinned(monkeypatch, open_pinned)
    result = main.dispatch(request)
    captured = capsys.readouterr()
    output = repr(result) + captured.out + captured.err + caplog.text
    assert "new.fixture" not in output and "new%2Efixture" not in output
    assert result["ok"] == (response_kind == "success")
    if response_kind == "success":
        response = result["result"]["response"]["data"]
        assert response["public"] == {"id": "42"}
        assert all(not item for item in response["credentials"])
        assert all("[redacted]" in url for url in response["urls"])
    else:
        assert result["error_code"] == "upstream_validation_failed"
