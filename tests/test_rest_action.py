"""Exercise all pinned REST routes through the workflow dispatcher."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import main
from runtime import rest
from runtime import rest_action
from test_flowsteward_discord import invocation

ROUTES = json.loads((Path(__file__).resolve().parents[1] / "runtime/rest_routes.json").read_text())


def sample_invocation(operation_id, route):
    write = route["method"] not in {"GET", "HEAD", "OPTIONS"}
    request = invocation("discord_rest_write" if write else "discord_rest_read")
    action = request["action"]
    connection = action["target"]["connection"]
    secret_names = set(route["secret_path_parameters"])
    if secret_names:
        connection["connection_type"] = "discord_route_token"
        connection["secrets"] = {name: "example.route.secret" for name in secret_names}
    elif not any("BotToken" in security for security in route["security"]):
        connection["connection_type"] = "discord_oauth_token"
        connection["secrets"] = {"access_token": "example.oauth.secret"}
    inputs = action["input"]
    inputs.update(
        operation_id=operation_id,
        path_parameters={
            name: "123" for name in route["path_parameters"] if name not in secret_names
        },
        query_parameters={name: "1" for name in route["required_query_parameters"]},
    )
    if route["request_body_required"]:
        inputs["body"] = {"data": {"name": "Example"}}
    return request, write


@pytest.mark.parametrize("operation_id", sorted(ROUTES))
def test_each_operation_reaches_its_registered_transport(monkeypatch, operation_id):
    route = ROUTES[operation_id]
    request, write = sample_invocation(operation_id, route)
    calls = []

    def send(**kwargs):
        calls.append(kwargs)
        status = kwargs["success_statuses"][0]
        return (
            status,
            "application/json",
            b'{"id":"123", "token":"sensitive"}' if status != 204 else b"",
        )

    monkeypatch.setattr(rest, "request_raw", send)
    result = main.dispatch(request)
    assert result["ok"] is True
    [call] = calls
    assert call["method"] == route["method"]
    assert call["success_statuses"] == tuple(route["success_statuses"])
    assert call["path"] == route["path"].format(
        **request["action"]["input"]["path_parameters"],
        **{name: "example.route.secret" for name in route["secret_path_parameters"]},
    )
    assert "sensitive" not in repr(result)
    assert ("external_effect_status" in result) == write


@pytest.mark.parametrize(
    "operation_id", sorted(oid for oid, row in ROUTES.items() if row["method"] != "GET")
)
def test_every_write_is_suppressed_in_test_runs(monkeypatch, operation_id):
    def unexpected(**kwargs):
        pytest.fail("Dry run must not call Discord")

    monkeypatch.setattr(rest, "request_raw", unexpected)
    request, _ = sample_invocation(operation_id, ROUTES[operation_id])
    request["runtime_context"]["test_mode"] = True
    assert main.dispatch(request) == {"ok": True, "result": {"response": {}, "suppressed": True}}


def test_mismatched_connection_and_method_are_rejected():
    route = ROUTES["get_current_user_application_entitlements"]
    request, _ = sample_invocation("get_current_user_application_entitlements", route)
    action = request["action"]
    action["target"]["connection"].update(
        connection_type="discord_bot", secrets={"bot_token": "example.bot"}
    )
    context = SimpleNamespace(raw={}, step_execution_id="step")
    assert (
        rest_action.dispatch_rest(action, action["input"], context, write=False, user_agent="Test")[
            "ok"
        ]
        is False
    )
    assert (
        rest_action.dispatch_rest(action, action["input"], context, write=True, user_agent="Test")[
            "ok"
        ]
        is False
    )


def test_multipart_sticker_payload_and_form_fields_are_encoded():
    request, _ = sample_invocation("create_guild_sticker", ROUTES["create_guild_sticker"])
    action = request["action"]
    action["input"].update(
        body={"data": {"name": "Example", "tags": "example"}},
        files=[{"field": "file", "filename": "example.png", "data_base64": "YWJj"}],
    )
    prepared = rest.prepare(
        "create_guild_sticker",
        inputs=action["input"],
        connection=action["target"]["connection"],
        write=True,
    )
    assert prepared.content_type.startswith("multipart/form-data; boundary=")
    assert b'name="name"\r\n\r\nExample\r\n' in prepared.body
    assert b'name="file"; filename="example.png"' in prepared.body


@pytest.mark.parametrize(
    ("mime", "raw", "expected"),
    [
        ("text/csv", b"id\n123\n", "id\n123\n"),
        ("image/png", b"\x89PNG", {"base64": "iVBORw=="}),
        ("application/json", b'{"note":"sample.bot.credential"}', {"note": "[redacted]"}),
    ],
)
def test_raw_responses_are_decoded_without_reflecting_credentials(monkeypatch, mime, raw, expected):
    request, _ = sample_invocation("get_channel", ROUTES["get_channel"])
    action = request["action"]
    prepared = rest.prepare(
        "get_channel",
        inputs=action["input"],
        connection=action["target"]["connection"],
        write=False,
    )
    monkeypatch.setattr(rest, "request_raw", lambda **kwargs: (200, mime, raw))
    assert rest.execute(prepared, user_agent="Test")["data"] == expected


def test_acknowledged_write_preserves_success_when_response_data_is_too_large(monkeypatch):
    from runtime.transport import DiscordResponseError

    def send(**kwargs):
        raise DiscordResponseError(200, "response_too_large")

    monkeypatch.setattr(rest, "request_raw", send)
    request, _ = sample_invocation("create_message", ROUTES["create_message"])
    result = main.dispatch(request)
    assert result["external_effect_status"] == "succeeded"
    assert result["result"]["response"]["warning"] == "response_too_large"
