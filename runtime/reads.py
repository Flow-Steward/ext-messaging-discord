"""Read-only Discord channel and guild operations."""

from __future__ import annotations

import re
from typing import Any

from runtime.rest import redact_response
from runtime.routes import request_target
from runtime.transport import request_json

SNOWFLAKE = re.compile(r"[0-9]{1,20}")
READ_OPERATIONS = {
    "get_channel": "channel_id",
    "list_messages": "channel_id",
    "get_guild": "guild_id",
    "list_guild_channels": "guild_id",
}
LIST_OPERATIONS = frozenset({"list_messages", "list_guild_channels"})
MESSAGE_CURSORS = frozenset({"before", "after", "around"})


def read_arguments(
    operation: str, inputs: dict[str, Any]
) -> tuple[dict[str, str], dict[str, str | int]]:
    path_name = READ_OPERATIONS[operation]
    path_value = inputs.get(path_name)
    if not isinstance(path_value, str) or not SNOWFLAKE.fullmatch(path_value):
        raise ValueError("A Discord snowflake ID is required")
    query: dict[str, str | int] = {}
    allowed = {"connection_ref", path_name}
    if operation == "get_guild":
        allowed.add("with_counts")
        if "with_counts" in inputs:
            counts = inputs["with_counts"]
            if not isinstance(counts, bool):
                raise ValueError("with_counts must be boolean")
            query["with_counts"] = "true" if counts else "false"
    if operation == "list_messages":
        allowed.update(MESSAGE_CURSORS | {"limit"})
        cursors = MESSAGE_CURSORS.intersection(inputs)
        if len(cursors) > 1:
            raise ValueError("Only one message cursor is allowed")
        for cursor in cursors:
            value = inputs[cursor]
            if not isinstance(value, str) or not SNOWFLAKE.fullmatch(value):
                raise ValueError("Message cursor must be a Discord snowflake")
            query[cursor] = value
        limit = inputs.get("limit", 25)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Message limit must be between 1 and 100")
        query["limit"] = limit
    if inputs.keys() - allowed:
        raise ValueError("Unexpected operation input")
    return {path_name: path_value}, query


def execute_read(
    operation: str,
    *,
    token: str,
    user_agent: str,
    path_parameters: dict[str, str],
    query: dict[str, str | int],
) -> dict[str, Any]:
    target = request_target(operation, path_parameters=path_parameters)
    data = request_json(
        method=target.method,
        path=target.path,
        token=token,
        user_agent=user_agent,
        success_statuses=target.success_statuses,
        query=query,
    )
    data = redact_response(data, (token,))
    if operation in LIST_OPERATIONS:
        if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
            raise ValueError("Unexpected Discord list response")
        return {"items": data}
    if not isinstance(data, dict):
        raise ValueError("Unexpected Discord object response")
    return {"item": data}
