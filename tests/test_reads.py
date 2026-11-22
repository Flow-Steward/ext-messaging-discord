"""Verify Discord read operations against the subprocess dispatcher."""

import pytest

import main
from runtime import reads
from test_flowsteward_discord import invocation


@pytest.mark.parametrize(
    ("operation", "inputs", "path", "query", "body", "result"),
    [
        ("get_channel", {"channel_id": "123"}, "/channels/123", {}, {"id": "123"}, "item"),
        (
            "list_messages",
            {"channel_id": "123", "before": "456", "limit": 10},
            "/channels/123/messages",
            {"before": "456", "limit": 10},
            [{"id": "456"}],
            "items",
        ),
        (
            "get_guild",
            {"guild_id": "789", "with_counts": False},
            "/guilds/789",
            {"with_counts": "false"},
            {"id": "789"},
            "item",
        ),
        ("list_guild_channels", {"guild_id": "789"}, "/guilds/789/channels", {}, [], "items"),
    ],
)
def test_reads_bind_inputs_and_preserve_provider_results(
    monkeypatch, operation, inputs, path, query, body, result
):
    calls = []

    def request_json(**kwargs):
        calls.append(kwargs)
        return body

    monkeypatch.setattr(reads, "request_json", request_json)
    payload = invocation(operation)
    payload["action"]["input"].update(inputs)
    assert main.dispatch(payload) == {"ok": True, "result": {result: body}}
    [request] = calls
    assert request["method"] == "GET"
    assert request["path"] == path
    assert request["query"] == query
    assert request["success_statuses"] == (200,)


def test_list_messages_rejects_incompatible_cursors_before_transport(monkeypatch):
    def unexpected(**kwargs):
        pytest.fail("Invalid input reached the transport")

    monkeypatch.setattr(reads, "request_json", unexpected)
    payload = invocation("list_messages")
    payload["action"]["input"].update(channel_id="123", before="456", after="789")
    assert main.dispatch(payload)["error_code"] == "invalid_payload"
