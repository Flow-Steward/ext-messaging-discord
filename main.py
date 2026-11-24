"""Discord extension subprocess entrypoint."""

from __future__ import annotations

import json
import re
import sys
from typing import Any

from flowsteward_extension_sdk import runtime_context_from_payload

from runtime.individual_actions import dispatch_individual
from runtime.reads import READ_OPERATIONS, read_arguments, shaped
from runtime.rest_action import connection_of, dispatch_rest, failure, test_run

USER_AGENT = "DiscordBot (https://github.com/Flow-Steward/ext-messaging-discord, 0.1.0)"
MAX_INPUT = 2_700_000
SNOWFLAKE = re.compile(r"[0-9]{1,20}")
TOKEN = re.compile(r"[A-Za-z0-9._-]{8,512}")
_failure = failure


def _bot_connection(action: dict[str, Any], inputs: dict[str, Any]) -> bool:
    connection = connection_of(action, inputs)
    if connection is None:
        return False
    connection_type = connection.get("connection_type_id") or connection.get("connection_type")
    secrets = connection.get("secrets")
    token = secrets.get("bot_token") if isinstance(secrets, dict) else None
    return (
        connection_type == "discord_bot" and isinstance(token, str) and bool(TOKEN.fullmatch(token))
    )


def _carry(response: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """The dedicated step's outputs on the outcome of the underlying REST call."""
    outcome = {key: value for key, value in response.items() if key != "result"}
    outcome["result"] = result
    return outcome


def _legacy(
    operation: str, action: dict[str, Any], inputs: dict[str, Any], context: Any
) -> dict[str, Any]:
    write = operation == "send_message"
    read = operation in READ_OPERATIONS
    channel_id, content = inputs.get("channel_id"), inputs.get("content")
    path_parameters: dict[str, str] = {}
    query: dict[str, str | int] = {}
    if read:
        try:
            path_parameters, query = read_arguments(operation, inputs)
        except ValueError:
            return _failure("invalid_payload")
    else:
        allowed = {"connection_ref", "channel_id", "content"} if write else {"connection_ref"}
        if inputs.keys() - allowed:
            return _failure("invalid_payload")
        if write and not (
            isinstance(channel_id, str)
            and SNOWFLAKE.fullmatch(channel_id)
            and isinstance(content, str)
            and content.strip()
            and len(content.encode("utf-16-le", errors="surrogatepass")) <= 4000
        ):
            return _failure("invalid_payload")
    test_mode = context.raw.get("test_mode", False)
    if not isinstance(test_mode, bool):
        return _failure("invalid_payload")
    if not _bot_connection(action, inputs):
        return _failure("invalid_connection")
    if write and test_mode:
        return test_run({"message_id": None, "channel_id": channel_id})

    rest_inputs: dict[str, Any] = {"connection_ref": inputs["connection_ref"]}
    if write:
        rest_inputs.update(
            operation_id="create_message",
            path_parameters={"channel_id": channel_id},
            body={"data": {"content": content, "allowed_mentions": {"parse": []}}},
        )
    elif read:
        rest_inputs.update(
            operation_id=operation,
            path_parameters=path_parameters,
            query_parameters={
                name: value for name, value in query.items() if not isinstance(value, bool)
            },
        )
    else:
        rest_inputs["operation_id"] = "get_my_user"
    response = dispatch_rest(
        action,
        rest_inputs,
        context,
        write=write,
        user_agent=USER_AGENT,
        all_pages=read and inputs.get("all_pages") is True,
    )
    outcome = response.get("result") or {}
    if not response["ok"]:
        return response
    data = (outcome.get("response") or {}).get("data")
    common = {"rate_limit": outcome.get("rate_limit"), "warnings": outcome.get("warnings", [])}
    if write:
        provider_id = data.get("id") if isinstance(data, dict) else None
        if not isinstance(provider_id, str) or not SNOWFLAKE.fullmatch(provider_id):
            provider_id = None
        return _carry(
            response,
            {
                "message_id": provider_id,
                "channel_id": channel_id,
                "suppressed": False,
                "processing": outcome.get("processing"),
                **common,
            },
        )
    if read:
        try:
            result = shaped(operation, data)
        except ValueError:
            return _failure("invalid_response", result={"rate_limit": outcome.get("rate_limit")})
        if operation == "list_messages":
            result.update(
                next_cursor=outcome.get("next_cursor"),
                complete=outcome.get("complete"),
                pages=outcome.get("pages"),
            )
        return _carry(response, {**result, **common})
    bot_id = data.get("id") if isinstance(data, dict) else None
    if not isinstance(bot_id, str) or not SNOWFLAKE.fullmatch(bot_id):
        return _failure("invalid_response", result={"rate_limit": outcome.get("rate_limit")})
    return _carry(response, {"bot_id": bot_id, **common})


def dispatch(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        context = runtime_context_from_payload(payload)
    except ValueError:
        return _failure("invalid_payload")
    action = payload.get("action")
    if payload.get("mode") != "action" or not isinstance(action, dict):
        return _failure("invalid_payload")
    operation = action.get("action_id") or action.get("operation_id")
    inputs = action.get("input", {})
    if not isinstance(operation, str) or not isinstance(inputs, dict):
        return _failure("invalid_payload")
    individual = dispatch_individual(operation, action, inputs, context, user_agent=USER_AGENT)
    if individual is not None:
        return individual
    if operation in {"discord_rest_read", "discord_rest_write"}:
        return dispatch_rest(
            action,
            inputs,
            context,
            write=operation == "discord_rest_write",
            user_agent=USER_AGENT,
        )
    if (
        operation == "send_message"
        or operation in READ_OPERATIONS
        or operation == "test_connection"
    ):
        return _legacy(operation, action, inputs, context)
    return _failure("invalid_payload")


def main() -> int:
    raw = sys.stdin.buffer.read(MAX_INPUT + 1)
    try:
        payload = json.loads(raw) if len(raw) <= MAX_INPUT else None
        response = dispatch(payload) if isinstance(payload, dict) else _failure("invalid_payload")
    except (UnicodeError, ValueError, RecursionError):
        response = _failure("invalid_payload")
    print(json.dumps(response))
    return 0 if response["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
