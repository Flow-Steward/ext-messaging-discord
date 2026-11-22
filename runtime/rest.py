"""Prepare and execute the pinned Discord REST operation catalog."""

from __future__ import annotations

import base64
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from runtime.routes import RequestTarget, request_target, route_for
from runtime.transport import DiscordResponseError, request_raw

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
TOKENIZED_PATH = re.compile(r"(/(?:webhooks|interactions)/[0-9]+/)[A-Za-z0-9._~-]+")


def _credential_field(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
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


def _multipart(body: Any, files: Any, *, raw_fields: bool = False) -> tuple[str, bytes]:
    if not isinstance(files, list) or len(files) > 10:
        raise ValueError("Multipart files must be a list of at most ten entries")
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
    used: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("Invalid multipart file")
        name = entry.get("field")
        filename = entry.get("filename")
        data = entry.get("data_base64")
        if (
            not isinstance(name, str)
            or not SAFE_NAME.fullmatch(name)
            or not isinstance(filename, str)
            or not SAFE_NAME.fullmatch(filename)
        ):
            raise ValueError("Invalid multipart field or filename")
        if name in used or not isinstance(data, str):
            raise ValueError("Invalid or duplicate multipart file")
        used.add(name)
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n".encode()
            + base64.b64decode(data, validate=True)
            + b"\r\n"
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    encoded = b"".join(chunks)
    if len(encoded) > MAX_UPLOAD:
        raise ValueError("Multipart body exceeds the upload budget")
    return f"multipart/form-data; boundary={boundary}", encoded


def prepare(
    operation_id: str, *, inputs: dict[str, Any], connection: dict[str, Any], write: bool
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
    body_input, files = inputs.get("body"), inputs.get("files", [])
    if body_input is not None and (not isinstance(body_input, dict) or set(body_input) != {"data"}):
        raise ValueError("The body must be wrapped in a data field")
    body = body_input["data"] if body_input is not None else None
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
    if body is not None or files:
        supported = route["request_media_types"]
        default = (
            "multipart/form-data"
            if files
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
            media_type, encoded = _multipart(
                body,
                files,
                raw_fields=operation_id
                in {
                    "create_guild_sticker",
                    "upload_application_attachment",
                    "update_invite_target_users",
                },
            )
        elif files:
            raise ValueError("Files require multipart/form-data")
        elif media_type == "application/json":
            encoded = json.dumps(body, allow_nan=False).encode()
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


def _redact(value: Any, credentials: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        return {
            key: _redact(item, credentials)
            for key, item in value.items()
            if not _credential_field(key) and all(token not in key for token in credentials)
        }
    if isinstance(value, list):
        return [_redact(item, credentials) for item in value]
    if isinstance(value, str):
        value = TOKENIZED_PATH.sub(r"\1[redacted]", value)
        for token in credentials:
            value = value.replace(token, "[redacted]")
    return value


def execute(prepared: Prepared, *, user_agent: str) -> dict[str, Any]:
    target = prepared.target
    try:
        status, media_type, raw = request_raw(
            method=target.method,
            path=target.path,
            authorization=prepared.authorization,
            user_agent=user_agent,
            success_statuses=target.success_statuses,
            data=prepared.body,
            content_type=prepared.content_type,
            query=prepared.query,
            audit_reason=prepared.audit_reason,
        )
    except DiscordResponseError as error:
        return {"status": error.status, "data": None, "warning": error.reason}
    if not raw:
        data = None
    elif media_type == "application/json":
        try:
            data = _redact(json.loads(raw), prepared.credentials)
        except (ValueError, RecursionError):
            return {
                "status": status,
                "media_type": media_type,
                "data": None,
                "warning": "invalid_json",
            }
    elif media_type == "text/csv":
        data = _redact(raw.decode(errors="replace"), prepared.credentials)
    elif media_type == "image/png":
        data = {"base64": base64.b64encode(raw).decode("ascii")}
    else:
        return {
            "status": status,
            "media_type": media_type,
            "data": None,
            "warning": "unexpected_content_type",
        }
    return {"status": status, "media_type": media_type, "data": data}
