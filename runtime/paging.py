"""Discord lists read page after page with an exact cursor.

Every GET operation of the pinned catalog whose query takes ``limit`` together with
``before`` and/or ``after`` is listed in ``PAGING`` (a test reconciles the table with the
specification). For each: where the page's items are (the answer itself, or a field of
it), which value of an item is the cursor, which directions Discord takes, and whether
the answer says ``has_more``. Sources: the endpoint pages of discord-api-docs and the
response schemas of discord-api-spec 3a21a01.

Going ``before`` continues from the smallest cursor of the items read, going ``after``
from the largest, whatever order Discord returns them in. A list is ``complete`` only
when Discord returns an empty page, or ``has_more: false`` where it reports it; a page
shorter than ``limit`` does not end the list.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

SNOWFLAKE = re.compile(r"(0|[1-9][0-9]{0,19})")


@dataclass(frozen=True)
class Paging:
    #: The answer's field holding the items, or None when the answer is the list.
    items: str | None
    #: The path to an item's cursor value.
    key: tuple[str, ...]
    #: Directions Discord accepts; the first is used when the step gives no cursor.
    directions: tuple[str, ...]
    #: "snowflake" (numeric id) or "timestamp" (ISO 8601).
    kind: str = "snowflake"
    #: The answer reports has_more.
    has_more: bool = False
    #: The documented maximum page size.
    max_limit: int = 100


PAGING: dict[str, Paging] = {
    # Entitlements: before/after entitlement id, 1-100.
    "get_entitlements": Paging(None, ("id",), ("after", "before")),
    # Channel messages: before/after message id, 1-100; around is one page only.
    "list_messages": Paging(None, ("id",), ("before", "after")),
    # Pinned messages: before a pin timestamp, 1-50, {items, has_more}.
    "list_pins": Paging(
        "items", ("pinned_at",), ("before",), kind="timestamp", has_more=True, max_limit=50
    ),
    # Users who reacted: after user id, 1-100.
    "list_message_reactions_by_emoji": Paging(None, ("id",), ("after",)),
    # Poll answer voters: after user id, 1-100, {users}.
    "get_answer_voters": Paging("users", ("id",), ("after",)),
    # Thread members: after user id, 1-100.
    "list_thread_members": Paging(None, ("user_id",), ("after",)),
    # Archived threads: before an archive timestamp, 2-100, {threads, members, has_more}.
    "list_private_archived_threads": Paging(
        "threads",
        ("thread_metadata", "archive_timestamp"),
        ("before",),
        kind="timestamp",
        has_more=True,
    ),
    "list_public_archived_threads": Paging(
        "threads",
        ("thread_metadata", "archive_timestamp"),
        ("before",),
        kind="timestamp",
        has_more=True,
    ),
    # Joined private archived threads: before thread id, 2-100.
    "list_my_private_archived_threads": Paging("threads", ("id",), ("before",), has_more=True),
    # Audit log: before/after entry id, 1-100, newest first by default.
    "list_guild_audit_log_entries": Paging("audit_log_entries", ("id",), ("before", "after")),
    # Bans: before/after user id, 1-1000.
    "list_guild_bans": Paging(None, ("user", "id"), ("after", "before"), max_limit=1000),
    # Guild members: after user id, 1-1000.
    "list_guild_members": Paging(None, ("user", "id"), ("after",), max_limit=1000),
    # Join requests: before/after request id, 1-100, {total, guild_join_requests}.
    "get_guild_join_requests": Paging("guild_join_requests", ("id",), ("after", "before")),
    # Scheduled event users: before/after user id, 1-100.
    "list_guild_scheduled_event_users": Paging(None, ("user_id",), ("after", "before")),
    "list_guild_scheduled_event_exception_users": Paging(None, ("user_id",), ("after", "before")),
    # SKU subscriptions: before/after subscription id, 1-100.
    "get_sku_subscriptions": Paging(None, ("id",), ("after", "before")),
    # Current user guilds: before/after guild id, 1-200.
    "list_my_guilds": Paging(None, ("id",), ("after", "before"), max_limit=200),
}


class PageShapeError(ValueError):
    """A page does not have the documented shape, so the list cannot go on exactly."""


def page_items(paging: Paging, data: Any) -> list[Any]:
    if data is None:
        return []
    container = (
        data if paging.items is None else data.get(paging.items) if isinstance(data, dict) else None
    )
    if not isinstance(container, list):
        raise PageShapeError("The page is not the documented list")
    return container


def cursor_of(paging: Paging, item: Any) -> str:
    node = item
    for name in paging.key:
        node = node.get(name) if isinstance(node, dict) else None
    if not isinstance(node, str):
        raise PageShapeError("An item has no cursor")
    if paging.kind == "snowflake":
        if not SNOWFLAKE.fullmatch(node):
            raise PageShapeError("An item's id is not a snowflake")
    else:
        _timestamp(node)
    return node


def _timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise PageShapeError("An item's timestamp is not ISO 8601") from None


def _order(paging: Paging, value: str) -> Any:
    return int(value) if paging.kind == "snowflake" else _timestamp(value)


def next_cursor(paging: Paging, items: list[Any], direction: str) -> str | None:
    """The cursor that continues after ``items`` in ``direction``."""
    cursors = [cursor_of(paging, item) for item in items]
    if not cursors:
        return None
    pick = min if direction == "before" else max
    return pick(cursors, key=lambda value: _order(paging, value))


def page_complete(paging: Paging, data: Any, items: list[Any]) -> bool:
    if not items:
        if paging.has_more and isinstance(data, dict) and data.get("has_more") is True:
            raise PageShapeError("An empty page says more items follow")
        return True
    if paging.has_more and isinstance(data, dict) and data.get("has_more") is False:
        return True
    return False


def merge(paging: Paging, pages: list[Any]) -> Any:
    """The pages as one answer of the documented shape."""
    if paging.items is None:
        return [item for page in pages for item in page_items(paging, page)]
    merged = dict(pages[0]) if isinstance(pages[0], dict) else {}
    for page in pages[1:]:
        if not isinstance(page, dict):
            continue
        for key, value in page.items():
            if isinstance(value, list) and isinstance(merged.get(key), list):
                if key == paging.items:
                    merged[key] = [*merged[key], *value]
                else:
                    seen = {json.dumps(item, sort_keys=True) for item in merged[key]}
                    merged[key] = [
                        *merged[key],
                        *(item for item in value if json.dumps(item, sort_keys=True) not in seen),
                    ]
            elif key == "has_more":
                merged[key] = value
            elif key not in merged:
                merged[key] = value
    return merged
