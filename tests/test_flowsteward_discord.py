import json
from urllib.error import URLError

import main
from discord_fakes import reply
from runtime import rest

CHANNEL = "123456789012345678"
MESSAGE = "987654321098765432"


def invocation(operation="send_message", *, test_mode=False):
    inputs = {"connection_ref": "connection-1"}
    if operation == "send_message":
        inputs.update(channel_id=CHANNEL, content="Hello @everyone")
    return {
        "contract_version": "extension_host_v2",
        "mode": "action",
        "runtime_context": {
            "group_id": None,
            "for_each_id": None,
            "step_id": "send",
            "step_execution_id": "execution-1",
            "test_mode": test_mode,
        },
        "action": {
            "action_id": operation,
            "input": inputs,
            "target": {
                "connection": {
                    "connection_id": "connection-1",
                    "connection_type": "discord_bot",
                    "secrets": {"bot_token": "sample.bot.credential"},
                }
            },
        },
    }


def unexpected(**kwargs):
    raise AssertionError("Unexpected outbound request")


def test_sends_one_message_and_disables_mentions(monkeypatch):
    calls = []

    def send(**kwargs):
        calls.append(kwargs)
        return reply(200, json.dumps({"id": MESSAGE, "content": "sample.bot.credential"}).encode())

    monkeypatch.setattr(rest, "request_raw", send)
    result = main.dispatch(invocation())
    assert result == {
        "ok": True,
        "result": {
            "message_id": MESSAGE,
            "channel_id": CHANNEL,
            "suppressed": False,
            "processing": "completed",
            "rate_limit": {
                "limit": None,
                "remaining": None,
                "reset_after": None,
                "bucket": None,
                "global": False,
            },
            "warnings": [],
        },
        "external_effect_status": "succeeded",
    }
    [call] = calls
    assert (call["method"], call["path"]) == ("POST", f"/channels/{CHANNEL}/messages")
    assert call["authorization"] == "Bot sample.bot.credential"
    body = json.loads(call["data"])
    assert body["content"] == "Hello @everyone"
    assert body["allowed_mentions"] == {"parse": []}
    assert body["enforce_nonce"] is True
    assert len(body["nonce"]) == 25


def test_connection_uses_bot_identity(monkeypatch):
    def send(**kwargs):
        assert (kwargs["method"], kwargs["path"]) == ("GET", "/users/@me")
        assert kwargs["authorization"] == "Bot sample.bot.credential"
        assert kwargs["data"] is None
        return reply(200, json.dumps({"id": MESSAGE}).encode())

    monkeypatch.setattr(rest, "request_raw", send)
    result = main.dispatch(invocation("test_connection"))
    assert result["ok"] is True
    assert result["result"]["bot_id"] == MESSAGE


def test_validates_target_and_suppresses_test_mode_writes(monkeypatch):
    monkeypatch.setattr(rest, "request_raw", unexpected)
    response = main.dispatch(invocation(test_mode=True))
    assert response["result"]["suppressed"] is True
    invalid = invocation()
    invalid["action"]["input"]["channel_id"] = "../users/@me"
    assert main.dispatch(invalid)["error_code"] == "invalid_payload"
    mismatched = invocation()
    mismatched["action"]["input"]["connection_ref"] = "different connection"
    assert main.dispatch(mismatched)["error_code"] == "invalid_connection"


def test_uncertain_write_is_not_retried_or_reflected(monkeypatch):
    calls = []

    def send(**kwargs):
        calls.append(kwargs)
        raise URLError("sample.bot.credential")

    monkeypatch.setattr(rest, "request_raw", send)
    response = main.dispatch(invocation())
    assert len(calls) == 1
    assert response["error_code"] == "timeout_unknown"
    assert response["external_effect_status"] == "timeout_unknown"
    assert response["definitely_no_external_effect"] is False
    assert "sample.bot.credential" not in repr(response)


def test_rejects_writes_without_a_logical_execution_id(monkeypatch):
    monkeypatch.setattr(rest, "request_raw", unexpected)
    request = invocation()
    request["runtime_context"].update(step_id=None, step_execution_id=None)
    assert main.dispatch(request)["error_code"] == "invalid_payload"


def test_dry_run_checks_that_the_connection_is_scoped_and_typed(monkeypatch):
    monkeypatch.setattr(rest, "request_raw", unexpected)
    request = invocation(test_mode=True)
    request["action"]["target"]["connection"].pop("connection_type")
    assert main.dispatch(request)["error_code"] == "invalid_connection"
    request = invocation(test_mode=True)
    request["action"]["input"].pop("connection_ref")
    assert main.dispatch(request)["error_code"] == "invalid_connection"
