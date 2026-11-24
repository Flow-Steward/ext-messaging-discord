"""Names, descriptions and groups of the Discord steps and their inputs.

The name and the first paragraph of each endpoint come from the Discord API
documentation at the pinned commit (tests/reference/discord-endpoint-docs.json, built
by tests/reference/extract_endpoint_docs.py). Twenty operations of the pinned API
description are not on a documentation page with a route; their sentence is below in
``UNDOCUMENTED``, from the API description where it has one, otherwise written from the
route itself.

An input with the same name means the same thing in every step, so it has one label and
one description (``COMMON``); every ID input ends in ``_id`` and is described the same
way. Query parameters take the description of the documentation table of their endpoint.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "tests/reference/discord-endpoint-docs.json"
#: The most characters of a step description taken from the documentation.
MAX_DESCRIPTION = 420

#: (title, description) of operations no documentation page shows with a route.
UNDOCUMENTED: dict[str, tuple[str, str]] = {
    "get_application": ("Get Application", "Returns an application by its ID."),
    "update_application": ("Modify Application", "Changes an application by its ID."),
    "upload_application_attachment": (
        "Upload Application Attachment",
        "Uploads a file as an attachment of the application.",
    ),
    "thread_search": ("Search Threads", "Searches the threads of a channel."),
    "get_guild_new_member_welcome": (
        "Get Guild New Member Welcome",
        "Returns the server's welcome settings for new members.",
    ),
    "get_guild_join_requests": (
        "Get Guild Join Requests",
        "List join requests for guild, optionally filtered by application status.",
    ),
    "action_guild_join_request": (
        "Action Guild Join Request",
        "Approve or reject guild join request.",
    ),
    "create_guild_scheduled_event_exception": (
        "Create Guild Scheduled Event Exception",
        "Create an exception to a recurring guild scheduled event.",
    ),
    "delete_guild_scheduled_event_exception": (
        "Delete Guild Scheduled Event Exception",
        "Delete an exception to a recurring guild scheduled event.",
    ),
    "update_guild_scheduled_event_exception": (
        "Modify Guild Scheduled Event Exception",
        "Modify an exception to a recurring guild scheduled event.",
    ),
    "count_guild_scheduled_event_users": (
        "Count Guild Scheduled Event Users",
        "Get the count of users subscribed to a guild scheduled event.",
    ),
    "list_guild_scheduled_event_exception_users": (
        "List Guild Scheduled Event Exception Users",
        "Get a list of users subscribed to a guild scheduled event exception.",
    ),
    "get_public_keys": (
        "Get OAuth2 Public Keys",
        "Returns Discord's OAuth2 public signing keys (a JSON Web Key Set).",
    ),
    "get_openid_connect_userinfo": (
        "Get OpenID Connect User Info",
        "Returns the OpenID Connect user information of the authorized user.",
    ),
    "update_user_message_external_moderation_metadata": (
        "Update User Message Moderation Metadata",
        "Update the external moderation metadata for a user message (DM).",
    ),
    "partner_sdk_token": (
        "Social SDK Token",
        "Exchanges an external account's credentials for a Discord provisional account "
        "token (Discord Social SDK).",
    ),
    "bot_partner_sdk_token": (
        "Social SDK Token (Bot)",
        "Exchanges an external account's credentials for a Discord provisional account "
        "token, authorized with the bot token (Discord Social SDK).",
    ),
    "partner_sdk_unmerge_provisional_account": (
        "Unmerge Provisional Account",
        "Separates a provisional account from the Discord account it was merged into "
        "(Discord Social SDK).",
    ),
    "bot_partner_sdk_unmerge_provisional_account": (
        "Unmerge Provisional Account (Bot)",
        "Separates a provisional account from the Discord account it was merged into, "
        "authorized with the bot token (Discord Social SDK).",
    ),
    "get_current_user_application_entitlements": (
        "Get Current User Application Entitlements",
        "Returns the authorized user's entitlements for an application.",
    ),
}

#: Inputs that mean the same in every step: (label, description).
COMMON: dict[str, tuple[str, str]] = {
    "audit_reason": (
        "Audit log reason",
        "Why the change is made; Discord shows it in the server's audit log (up to 512 "
        "characters).",
    ),
    "body": (
        "Request body",
        'The request body as JSON inside data, for example {"data": {"content": '
        '"Hello"}}, with the fields the Discord documentation lists for this step. '
        "Credentials come from the connection, never from here.",
    ),
    "files": (
        "Files (base64)",
        "Small files as base64: for each, the multipart field (for example files[0]), the "
        "file name and the contents. Send larger files (up to 20 MiB each) in Workflow "
        "files.",
    ),
    "file_artifacts": (
        "Workflow files",
        "Files from earlier steps, up to 20 MiB each: for each, the multipart field (for "
        "example files[0] or file), the file name and the workflow file. The file name's "
        "extension sets the Content-Type.",
    ),
    "all_pages": (
        "All pages",
        "Read page after page until Discord's list ends, or the step's time or output is "
        "used up; then complete is false and next_cursor says where to continue.",
    ),
    "media_type": (
        "Body format",
        "How the body is sent: JSON, or multipart/form-data when files go with it.",
    ),
    "path_parameters": (
        "Path parameters",
        'The values of the operation\'s path, by name, for example {"channel_id": "123"}.',
    ),
    "query_parameters": (
        "Query parameters",
        "The operation's query parameters, by name.",
    ),
    "operation_id": ("Discord operation", "The Discord operation this step calls."),
    "content": ("Message text", "The text of the message, up to 2000 characters."),
}

#: Inputs that are not IDs but name one thing in the path, and query parameters the
#: documentation of their endpoint has no table for: (label, description).
NAMED: dict[str, tuple[str, str]] = {
    "code": ("Code", "The invite or template code (the last part of its link)."),
    "emoji_name": (
        "Emoji",
        "The emoji: a Unicode emoji, or name:id for a custom emoji (URL-encoded by the step).",
    ),
    "provider_type": ("Identity provider type", "The type of the external identity provider."),
    "after": ("After", "Only items after this ID (a Discord snowflake)."),
    "before": ("Before", "Only items before this ID (a Discord snowflake)."),
    "limit": ("Limit", "The most items Discord returns in one page."),
    "status": ("Status", "Only join requests with this application status."),
    "with_member": ("With member", "Include each user's server member object."),
    "sort_by": ("Sort by", "The field the results are sorted by."),
    "sort_order": ("Sort order", "asc or desc."),
    "archived": ("Archived", "Search archived threads (true) or active ones (false)."),
    "exclude_consumed": ("Exclude consumed", "Leave out entitlements that were consumed."),
    "only_active": ("Only active", "Only entitlements that are active now."),
    "name": ("Name", "Text to search for in thread names (up to 100 characters)."),
    "offset": ("Offset", "How many results to skip, for the next page of a search."),
    "slop": ("Slop", "How far apart the search words may be (0-100)."),
    "tag": ("Tags", "Forum tag IDs the threads must have."),
    "tag_setting": ("Tag matching", "Whether a thread must have all of the tags or any of them."),
    "with_components": (
        "With components",
        "Respect the components field of the request (application-owned webhooks may then "
        "use all components).",
    ),
    "user_id_1": ("First user ID", "The ID of the first user in the DM."),
    "user_id_2": ("Second user ID", "The ID of the second user in the DM."),
    "with_counts": (
        "With counts",
        "Include the approximate member and presence counts of the server.",
    ),
}

#: Words of an ID input's name, where they are not the name itself.
_ID_NOUNS = {
    "guild": "server",
    "guild_scheduled_event": "scheduled event",
    "guild_scheduled_event_exception": "scheduled event exception",
    "provider_issued_user": "user, as the identity provider issued it",
    "request": "join request",
    "rule": "auto moderation rule",
    "overwrite": "permission overwrite (role or user)",
    "sound": "soundboard sound",
    "instance": "activity instance",
    "answer": "poll answer",
    "integration": "integration",
    "pack": "sticker pack",
    "author": "author",
    "max": "largest",
    "min": "smallest",
}
_ACRONYMS = {"id": "ID", "ids": "IDs", "sku": "SKU", "url": "URL", "mfa": "MFA"}


def label_of(name: str) -> str:
    words = name.split("_")
    out = [_ACRONYMS.get(w, w) for w in words]
    text = " ".join(out)
    return text[:1].upper() + text[1:]


def id_description(name: str) -> str | None:
    """One sentence for every ``*_id`` input (and ``*_ids`` lists)."""
    for suffix, plural in (("_ids", True), ("_id", False)):
        if name.endswith(suffix):
            stem = name[: -len(suffix)]
            noun = _ID_NOUNS.get(stem, stem.replace("_", " "))
            if stem in {"max", "min"}:
                return f"Only items whose ID is at most / at least this ({noun} ID)."
            if plural:
                return f"The IDs of the {noun}s (Discord snowflakes)."
            return f"The ID of the {noun} (a Discord snowflake, digits only)."
    return None


def endpoint_docs() -> dict[str, dict[str, Any]]:
    return json.loads(DOCS.read_text())["endpoints"]


def route_key(method: str, path: str) -> str:
    return f"{method} {re.sub(r'{[^}]+}', '{}', path)}"


def _sentences(text: str, limit: int) -> str:
    """Whole sentences of ``text`` within ``limit`` characters."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind(".) "))
    return cut[: end + 1] if end > 0 else cut.rsplit(" ", 1)[0] + "…"


def describe(operation_id: str, method: str, path: str) -> tuple[str, str, str]:
    """(title, description, source page) of a Discord operation."""
    found = endpoint_docs().get(route_key(method, path))
    if found and found["description"]:
        return found["title"], _sentences(found["description"], MAX_DESCRIPTION), found["page"]
    if operation_id in UNDOCUMENTED:
        title, text = UNDOCUMENTED[operation_id]
        return title, text, ""
    raise ValueError(f"No description for {operation_id} ({method} {path})")


def field_doc(name: str, location: str, method: str, path: str) -> tuple[str, str]:
    """(label, description) of one input of a step."""
    if name in COMMON:
        return COMMON[name]
    plain = name.removeprefix("path_").removeprefix("query_")
    described = id_description(plain)
    if described and location == "path":
        return label_of(plain), described
    found = endpoint_docs().get(route_key(method, path)) or {}
    table = {
        row["name"]: row["description"] for row in (found.get("params") or {}).get("query", [])
    }
    if location == "query" and plain in table and table[plain]:
        text = table[plain]
        if described and not text.lower().startswith("filter"):
            # An ID in the query names one thing, like an ID in the path.
            return label_of(plain), described
        # A filter of a search takes its own label: it is not the thing the step acts on.
        label = label_of(plain) + (" filter" if described else "")
        return label, text[:1].upper() + text[1:]
    if plain in NAMED:
        return NAMED[plain]
    if described:
        return label_of(plain), described
    raise ValueError(f"No description for input {name} of {method} {path}")


#: The groups of the API pages, in page order: (id, title, one line).
GROUPS: list[tuple[str, str, str]] = [
    ("messages", "Messages", "Send, read, edit, pin and delete messages, reactions and polls."),
    (
        "channels",
        "Channels and threads",
        "Read, create and change channels, threads, permissions, invites and stage instances.",
    ),
    (
        "guilds",
        "Servers and members",
        "Read and change servers, their members, onboarding, widgets, templates and voice states.",
    ),
    ("roles", "Roles", "Create, change, order and delete roles, and give them to members."),
    (
        "moderation",
        "Moderation and audit log",
        "Bans, pruning, join requests, auto moderation rules and the audit log.",
    ),
    ("webhooks", "Webhooks", "Create and change webhooks and post messages through them."),
    (
        "emojis",
        "Emojis, stickers and sounds",
        "Server and application emojis, stickers and soundboard sounds.",
    ),
    (
        "events",
        "Scheduled events",
        "Create and change scheduled events, their exceptions and their subscribers.",
    ),
    (
        "applications",
        "Applications, commands and interactions",
        "The application itself, its slash commands and permissions, role connections, "
        "interaction responses and the Gateway address.",
    ),
    (
        "lobbies",
        "Lobbies and Social SDK",
        "Lobbies, provisional accounts and application identities of the Discord Social SDK.",
    ),
    ("monetization", "Monetization", "SKUs, entitlements and subscriptions."),
    (
        "users",
        "Users and OAuth2",
        "The current user, their servers, connections and DMs, and OAuth2 information.",
    ),
]

#: (group, test on "page|method path|operation_id"), first match wins.
_RULES: list[tuple[str, str]] = [
    ("webhooks", r"/webhooks"),
    ("roles", r"/roles"),
    ("moderation", r"/bans|/bulk-ban|/prune|/audit-logs|/auto-moderation|/requests|moderation"),
    ("events", r"scheduled-event"),
    ("emojis", r"/emojis|/stickers|/sticker-packs|soundboard"),
    ("monetization", r"/skus|/entitlements|/subscriptions"),
    ("lobbies", r"/lobbies|partner-sdk|application-identit|/identities/|social-sdk"),
    (
        "applications",
        r"/commands|/interactions|/applications|role-connections|/activity-instances|/gateway",
    ),
    ("messages", r"/messages|/polls|/pins|/reactions|message\.mdx|poll\.mdx"),
    ("channels", r"^[^|]*channel\.mdx|/channels/|/threads|stage-instance|/invites/"),
    ("users", r"/users/|/oauth2|user\.mdx"),
    ("guilds", r"/guilds|/voice|guild"),
]


def group_of(operation_id: str, method: str, path: str) -> str:
    page = (endpoint_docs().get(route_key(method, path)) or {}).get("page", "")
    text = f"{page}|{method} {path}|{operation_id}"
    for group, rule in _RULES:
        if re.search(rule, text):
            return group
    raise ValueError(f"No group for {operation_id} ({method} {path})")
