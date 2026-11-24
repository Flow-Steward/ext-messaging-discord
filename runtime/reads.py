"""Read-only Discord channel and guild operations."""

from __future__ import annotations

import re
from typing import Any


SNOWFLAKE = re.compile(r"[0-9]{1,20}")
READ_OPERATIONS = {
    "get_channel": "channel_id",
    "list_messages": "channel_id",
    "get_guild": "guild_id",
    "list_guild_channels": "guild_id",
}
LIST_OPERATIONS = frozenset({"list_messages", "list_guild_channels"})
MESSAGE_CURSORS = frozenset({"before", "after", "around"})
#: Get Channel Messages takes limit "Max number of messages to return (1-100)"
#: (discord-api-docs, channel.mdx).
MAX_MESSAGE_LIMIT = 100
#: Messages a single read returns when no limit is given (our default; all_pages asks
#: for the most per page).
DEFAULT_MESSAGE_LIMIT = 25


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
        allowed.update(MESSAGE_CURSORS | {"limit", "all_pages"})
        if "all_pages" in inputs and not isinstance(inputs["all_pages"], bool):
            raise ValueError("all_pages must be boolean")
        cursors = MESSAGE_CURSORS.intersection(inputs)
        if len(cursors) > 1:
            raise ValueError("Only one message cursor is allowed")
        for cursor in cursors:
            value = inputs[cursor]
            if not isinstance(value, str) or not SNOWFLAKE.fullmatch(value):
                raise ValueError("Message cursor must be a Discord snowflake")
            query[cursor] = value
        default = MAX_MESSAGE_LIMIT if inputs.get("all_pages") is True else DEFAULT_MESSAGE_LIMIT
        limit = inputs.get("limit", default)
        if type(limit) is not int or not 1 <= limit <= MAX_MESSAGE_LIMIT:
            raise ValueError(f"Message limit must be between 1 and {MAX_MESSAGE_LIMIT}")
        query["limit"] = limit
    if inputs.keys() - allowed:
        raise ValueError("Unexpected operation input")
    return {path_name: path_value}, query


def shaped(operation: str, data: Any) -> dict[str, Any]:
    """The legacy outputs: ``items`` (a list of objects) or ``item`` (an object)."""
    if operation in LIST_OPERATIONS:
        items = [] if data is None else data
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ValueError("Unexpected Discord list response")
        return {"items": items}
    if not isinstance(data, dict):
        raise ValueError("Unexpected Discord object response")
    return {"item": data}
