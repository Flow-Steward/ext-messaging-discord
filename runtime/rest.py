"""Prepare and execute the pinned Discord REST operation catalog."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, unquote, urlencode

from runtime.files import ArtifactReader, Part, file_parts
from runtime.routes import RequestTarget, request_target, route_for
from runtime.transport import DEFAULT_TIMEOUT_SECONDS, Reply, request_raw

MAX_UPLOAD = 2_000_000
SAFE_NAME = re.compile(r"[A-Za-z0-9_.\[\]-]{1,160}")
CREDENTIAL = re.compile(r"[A-Za-z0-9._~-]{1,512}")
SECRET_FIELDS = frozenset(
    {
        "token",
        "access_token",
        "refresh_token",
        "bot_token",
        "webhook_token",
        "interaction_token",
        "client_secret",
        "authorization",
        "password",
        "secret",
    }
)


# Provider credentials in JSON bodies come from the connection, never step inputs.
BODY_CREDENTIALS = {
    "add_group_dm_user": {"access_token"},
    "add_guild_member": {"access_token"},
    "create_or_join_lobby": {"secret"},
    "partner_sdk_token": {"client_secret", "external_auth_token"},
    "partner_sdk_unmerge_provisional_account": {"client_secret", "external_auth_token"},
}
SECRET_SUFFIXES = ("_token", "_secret", "_password", "_api_key", "_private_key")
TOKENIZED_PATH = re.compile(
    r"(/(?:webhooks|interactions)/[0-9]+/)((?:[A-Za-z0-9._~-]|%[0-9A-Fa-f]{2})+)",
    re.IGNORECASE,
)
AUTH_TOKEN = re.compile(r"(?<![A-Za-z0-9._~-])(?:Bot|Bearer)\s+([A-Za-z0-9._~-]+)", re.IGNORECASE)
TOKEN_QUERY = re.compile(
    r"([?&](?:access_token|refresh_token|bot_token|webhook_token|interaction_token|token)=)"
    r"([^&#\s]+)",
    re.IGNORECASE,
)


def _credential_field(key: str) -> bool:
    normalized = re.sub(r"([a-z])([A-Z])", r"\1_\2", key).casefold().replace("-", "_")
    return normalized in SECRET_FIELDS or normalized.endswith(SECRET_SUFFIXES)


@dataclass(frozen=True)
class Prepared:
    target: RequestTarget
    authorization: str | None = field(repr=False)
    credentials: tuple[str, ...] = field(repr=False)
    content_type: str | None
    body: bytes | None = field(repr=False)
    query: list[tuple[str, str]]
    audit_reason: str


def _pairs(values: dict[str, Any]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for key, value in values.items():
        entries = value if isinstance(value, list) else [value]
        for item in entries:
            if isinstance(item, bool):
                pairs.append((key, str(item).lower()))
            elif isinstance(item, (str, int)):
                pairs.append((key, str(item)))
            elif item is not None:
                raise ValueError("Parameter values must be strings, integers or booleans")
    return pairs


def _multipart(body: Any, parts: list[Part], *, raw_fields: bool = False) -> tuple[str, bytes]:
    boundary = uuid.uuid4().hex
    chunks: list[bytes] = []
    if raw_fields and body is not None:
        if not isinstance(body, dict):
            raise ValueError("Multipart fields must be an object")
        for field_name, value in _pairs(body):
            if not SAFE_NAME.fullmatch(field_name):
                raise ValueError("Invalid multipart field")
            chunks.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{field_name}"\r\n\r\n'.encode()
                + value.encode()
                + b"\r\n"
            )
    elif body is not None:
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
            "Content-Type: application/json\r\n\r\n".encode()
            + json.dumps(body, allow_nan=False).encode()
            + b"\r\n"
        )
    for part in parts:
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{part.name}"; '
            f'filename="{part.filename}"\r\nContent-Type: {part.content_type}\r\n\r\n'.encode()
            + part.data
            + b"\r\n"
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    encoded = b"".join(chunks)
    if len(encoded) > MAX_UPLOAD:
        raise ValueError("Multipart body exceeds the upload budget")
    return f"multipart/form-data; boundary={boundary}", encoded


def prepare(
    operation_id: str,
    *,
    inputs: dict[str, Any],
    connection: dict[str, Any],
    write: bool,
    read_artifact: ArtifactReader | None = None,
) -> Prepared:
    route = route_for(operation_id)
    if (route["method"] not in {"GET", "HEAD", "OPTIONS"}) != write:
        raise ValueError("Select the matching read or write action")
    if inputs.keys() - {
        "connection_ref",
        "operation_id",
        "path_parameters",
        "query_parameters",
        "body",
        "media_type",
        "files",
        "file_artifacts",
        "audit_reason",
    }:
        raise ValueError("Unsupported input field")
    secrets = connection.get("secrets")
    if not isinstance(secrets, dict):
        raise ValueError("Connection credentials are required")
    connection_type = connection.get("connection_type_id") or connection.get("connection_type")
    path_names = route["secret_path_parameters"]
    authorization = None
    route_secrets: dict[str, str] = {}
    if path_names:
        if connection_type != "discord_route_token":
            raise ValueError("A Discord route token connection is required")
        for name in path_names:
            token = secrets.get(name)
            if not isinstance(token, str) or not CREDENTIAL.fullmatch(token):
                raise ValueError("The route token is missing")
            route_secrets[name] = token
    else:
        auth_types = {
            "discord_bot": ("BotToken", "Bot", "bot_token"),
            "discord_oauth_token": ("OAuth2", "Bearer", "access_token"),
        }
        if connection_type not in auth_types:
            raise ValueError("Select a compatible Discord connection")
        scheme, prefix, key = auth_types[connection_type]
        if not any(scheme in alternative for alternative in route["security"]):
            raise ValueError("The selected credential type cannot invoke this operation")
        token = secrets.get(key)
        if not isinstance(token, str) or not CREDENTIAL.fullmatch(token):
            raise ValueError("The credential is missing or invalid")
        authorization = f"{prefix} {token}"

    paths, query = inputs.get("path_parameters", {}), inputs.get("query_parameters", {})
    if not isinstance(paths, dict) or not isinstance(query, dict):
        raise ValueError("Path and query parameters must be objects")
    if query.keys() - set(route["query_parameters"]) or not set(
        route["required_query_parameters"]
    ).issubset(query):
        raise ValueError("Query parameters do not match this operation")
    target = request_target(operation_id, path_parameters=paths, connection_secrets=route_secrets)
    reason = inputs.get("audit_reason", "")
    if not isinstance(reason, str) or len(reason) > 512:
        raise ValueError("Audit reason exceeds the limit")
    body_input = inputs.get("body")
    files = inputs.get("files", [])
    artifacts = inputs.get("file_artifacts", [])
    if body_input is not None and (not isinstance(body_input, dict) or set(body_input) != {"data"}):
        raise ValueError("The body must be wrapped in a data field")
    body = body_input["data"] if body_input is not None else None
    if operation_id == "update_application_identity_profile" and isinstance(body, dict):
        profile = body.get("data")
        if (
            profile is not None
            and len(json.dumps(profile, ensure_ascii=False, separators=(",", ":")).encode())
            > 10_000
        ):
            raise ValueError("Profile data exceeds Discord's limit")
    credential_names = BODY_CREDENTIALS.get(operation_id, set())
    if credential_names:
        if not isinstance(body, dict) or credential_names.intersection(body):
            raise ValueError("Body credentials must come from the selected connection")
        body = {
            **body,
            **{
                name: value
                for name in credential_names
                if isinstance(value := secrets.get(name), str) and value
            },
        }
    media_type, encoded = None, None
    if body is not None or files or artifacts:
        supported = route["request_media_types"]
        default = (
            "multipart/form-data"
            if files or artifacts
            else "application/json"
            if "application/json" in supported
            else supported[0]
            if supported
            else ""
        )
        media_type = inputs.get("media_type", default)
        if media_type not in supported:
            raise ValueError("Content type is not supported by this operation")
        if media_type == "multipart/form-data":
            parts = file_parts(
                operation_id,
                files,
                artifacts,
                read_artifact=read_artifact,
                valid_name=lambda name: SAFE_NAME.fullmatch(name) is not None,
            )
            media_type, encoded = _multipart(
                body,
                parts,
                raw_fields=operation_id
                in {
                    "create_guild_sticker",
                    "upload_application_attachment",
                    "update_invite_target_users",
                },
            )
        elif files or artifacts:
            raise ValueError("Files require multipart/form-data")
        elif media_type == "application/json":
            encoded = json.dumps(
                body, allow_nan=False, ensure_ascii=False, separators=(",", ":")
            ).encode()
        elif media_type == "application/x-www-form-urlencoded" and isinstance(body, dict):
            encoded = urlencode(_pairs(body)).encode()
        else:
            raise ValueError("Unsupported request body")
        if len(encoded) > MAX_UPLOAD:
            raise ValueError("Request body exceeds the upload budget")
    elif route["request_body_required"]:
        raise ValueError("Request body is required")

    credentials = tuple(value for value in secrets.values() if isinstance(value, str) and value)
    return Prepared(target, authorization, credentials, media_type, encoded, _pairs(query), reason)


#: A value found in the response under a credential field name is removed from every
#: other text only when it is at least this long; a short value ("1") would otherwise
#: corrupt unrelated text ("room 101"). The connection's own secrets are always removed.
MIN_COLLECTED_SECRET = 8


def redact_response(value: Any, credentials: tuple[str, ...]) -> Any:
    tokens = set(credentials)

    def collect(node: Any) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                if (
                    _credential_field(key)
                    and isinstance(item, str)
                    and len(item) >= MIN_COLLECTED_SECRET
                ):
                    tokens.add(item)
                collect(item)
        elif isinstance(node, list):
            for item in node:
                collect(item)
        elif isinstance(node, str):
            tokens.update(unquote(match[2]) for match in TOKENIZED_PATH.finditer(node))
            tokens.update(unquote(match[2]) for match in TOKEN_QUERY.finditer(node))
            tokens.update(match[1] for match in AUTH_TOKEN.finditer(node))

    collect(value)
    variants = sorted(
        tokens | {quote(token, safe="") for token in tokens}, key=lambda token: (-len(token), token)
    )

    def scrub(node: Any) -> Any:
        if isinstance(node, dict):
            return {
                key: scrub(item)
                for key, item in node.items()
                if not _credential_field(key) and scrub(key) == key
            }
        if isinstance(node, list):
            return [scrub(item) for item in node]
        if isinstance(node, str):
            node = TOKENIZED_PATH.sub(r"\1[redacted]", node)
            node = TOKEN_QUERY.sub(r"\1[redacted]", node)
            for token in variants:
                node = node.replace(token, "[redacted]")
            node = AUTH_TOKEN.sub("[redacted]", node)
        return node

    return scrub(value)


def execute(
    prepared: Prepared, *, user_agent: str, timeout: float = DEFAULT_TIMEOUT_SECONDS
) -> Reply:
    """Send the prepared request once."""
    target = prepared.target
    return request_raw(
        method=target.method,
        path=target.path,
        authorization=prepared.authorization,
        user_agent=user_agent,
        success_statuses=target.success_statuses,
        data=prepared.body,
        content_type=prepared.content_type,
        query=prepared.query,
        audit_reason=prepared.audit_reason,
        timeout=timeout,
    )
