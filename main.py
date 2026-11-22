"""Discord extension subprocess entrypoint."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from typing import Any
from urllib.error import URLError

from flowsteward_extension_sdk import runtime_context_from_payload

from runtime.reads import READ_OPERATIONS, execute_read, read_arguments
from runtime.routes import RequestTarget, request_target
from runtime.transport import DiscordHTTPError, request_json

USER_AGENT = "DiscordBot (https://github.com/Flow-Steward, 0.1.0)"
MAX_INPUT = 32_768
SNOWFLAKE = re.compile(r"[0-9]{1,20}")
TOKEN = re.compile(r"[A-Za-z0-9._-]{1,512}")
STATUS_ERRORS = {
    400: "upstream_validation_failed",
    401: "authentication_failed",
    403: "access_denied",
    404: "not_found",
    429: "rate_limited",
}


def _failure(code: str, *, uncertain: bool = False) -> dict[str, Any]:
    return {
        "ok": False,
        "result": {},
        "error_code": code,
        "error": code.replace("_", " "),
        "definitely_no_external_effect": not uncertain,
        "external_effect_status": "timeout_unknown" if uncertain else "failed",
    }


def _request(target: RequestTarget, token: str, body: dict | None = None) -> dict:
    result = request_json(
        method=target.method,
        path=target.path,
        token=token,
        user_agent=USER_AGENT,
        success_statuses=target.success_statuses,
        body=body,
    )
    if not isinstance(result, dict):
        raise ValueError("Discord response was not an object")
    return result


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
    write = operation == "send_message"
    read = operation in READ_OPERATIONS
    if not (write or read or operation == "test_connection"):
        return _failure("invalid_payload")
    channel_id, content = inputs.get("channel_id"), inputs.get("content")
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
    target = action.get("target")
    connection = target.get("connection") if isinstance(target, dict) else None
    connection_ref = inputs.get("connection_ref")
    if not isinstance(connection, dict) or not connection.get("connection_id"):
        return _failure("invalid_connection")
    if not isinstance(connection_ref, str) or not connection_ref:
        return _failure("invalid_connection")
    if connection["connection_id"] != connection_ref:
        return _failure("invalid_connection")
    connection_type = connection.get("connection_type_id") or connection.get("connection_type")
    if connection_type != "discord_bot":
        return _failure("invalid_connection")
    secrets = connection.get("secrets")
    token = secrets.get("bot_token") if isinstance(secrets, dict) else None
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        return _failure("invalid_connection")

    if write and test_mode:
        return {
            "ok": True,
            "result": {"message_id": "", "channel_id": channel_id, "suppressed": True},
        }

    body: dict[str, Any] | None = None
    request = request_target("get_my_user")
    if write:
        execution_id = context.step_execution_id
        if not execution_id:
            return _failure("invalid_payload")
        request = request_target("create_message", path_parameters={"channel_id": channel_id})
        body = {
            "content": content,
            "allowed_mentions": {"parse": []},
            "nonce": hashlib.sha256(execution_id.encode()).hexdigest()[:25],
            "enforce_nonce": True,
        }
    try:
        if read:
            return {
                "ok": True,
                "result": execute_read(
                    operation,
                    token=token,
                    user_agent=USER_AGENT,
                    path_parameters=path_parameters,
                    query=query,
                ),
            }
        response = _request(request, token, body)
        provider_id = response.get("id")
        if not isinstance(provider_id, str) or not SNOWFLAKE.fullmatch(provider_id):
            raise ValueError("Discord response did not contain an ID")
    except DiscordHTTPError as exc:
        if exc.status in STATUS_ERRORS:
            failure = _failure(STATUS_ERRORS[exc.status])
            if exc.code is not None:
                failure["provider_error_code"] = exc.code
            if exc.retry_after is not None:
                failure["retry_after_seconds"] = exc.retry_after
            return failure
        return _failure("timeout_unknown" if write else "provider_unavailable", uncertain=write)
    except (URLError, OSError, ValueError, RecursionError):
        return _failure("timeout_unknown" if write else "provider_unavailable", uncertain=write)

    if write:
        return {
            "ok": True,
            "result": {"message_id": provider_id, "channel_id": channel_id, "suppressed": False},
            "external_effect_status": "succeeded",
        }
    return {"ok": True, "result": {"bot_id": provider_id}}


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
