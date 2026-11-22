from urllib.error import URLError

import main

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


def test_sends_one_message_and_disables_mentions(monkeypatch):
    calls = []

    def request(path, token, body):
        calls.append((path, token, body))
        return {"id": MESSAGE, "content": "sample.bot.credential"}

    monkeypatch.setattr(main, "_request", request)
    result = main.dispatch(invocation())
    assert result == {
        "ok": True,
        "result": {"message_id": MESSAGE, "channel_id": CHANNEL, "suppressed": False},
        "external_effect_status": "succeeded",
    }
    [(path, token, body)] = calls
    assert path == f"/channels/{CHANNEL}/messages"
    assert token == "sample.bot.credential"
    assert body["content"] == "Hello @everyone"
    assert body["allowed_mentions"] == {"parse": []}
    assert body["enforce_nonce"] is True
    assert len(body["nonce"]) == 25


def test_connection_uses_bot_identity(monkeypatch):
    def request(path, token, body):
        assert path == "/users/@me"
        assert token == "sample.bot.credential"
        assert body is None
        return {"id": MESSAGE}

    monkeypatch.setattr(main, "_request", request)
    assert main.dispatch(invocation("test_connection")) == {
        "ok": True,
        "result": {"bot_id": MESSAGE},
    }


def test_validates_target_and_suppresses_test_mode_writes(monkeypatch):
    def unexpected(*args):
        raise AssertionError("Unexpected outbound request")

    monkeypatch.setattr(main, "_request", unexpected)
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

    def request(*args):
        calls.append(args)
        raise URLError("sample.bot.credential")

    monkeypatch.setattr(main, "_request", request)
    response = main.dispatch(invocation())
    assert len(calls) == 1
    assert response["error_code"] == "timeout_unknown"
    assert response["external_effect_status"] == "timeout_unknown"
    assert response["definitely_no_external_effect"] is False
    assert "sample.bot.credential" not in repr(response)


def test_rejects_writes_without_a_logical_execution_id(monkeypatch):
    def unexpected(*args):
        raise AssertionError("Unexpected outbound request")

    monkeypatch.setattr(main, "_request", unexpected)
    request = invocation()
    request["runtime_context"].update(step_id=None, step_execution_id=None)
    assert main.dispatch(request)["error_code"] == "invalid_payload"


def test_dry_run_checks_that_the_connection_is_scoped_and_typed(monkeypatch):
    def unexpected(*args):
        raise AssertionError("Unexpected outbound request")

    monkeypatch.setattr(main, "_request", unexpected)
    request = invocation(test_mode=True)
    request["action"]["target"]["connection"].pop("connection_type")
    assert main.dispatch(request)["error_code"] == "invalid_connection"
    request = invocation(test_mode=True)
    request["action"]["input"].pop("connection_ref")
    assert main.dispatch(request)["error_code"] == "invalid_connection"
