"""Resolve registered Discord REST operations to fixed request targets."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

TOKEN = re.compile(r"[A-Za-z0-9._-]{1,512}")
PLACEHOLDER = re.compile(r"\{([a-zA-Z0-9_]+)\}")
#: A path parameter as this extension accepts it (our bound, as for a token).
MAX_PATH_VALUE = 512
_ROUTE_DATA = json.loads(Path(__file__).with_name("rest_routes.json").read_text())


@dataclass(frozen=True)
class RequestTarget:
    method: str
    path: str = field(repr=False)
    success_statuses: tuple[int, ...]


def route_for(operation_id: str) -> dict[str, Any]:
    row = _ROUTE_DATA.get(operation_id)
    if row is None:
        raise ValueError("Unregistered Discord API operation")
    return row


def request_target(
    operation_id: str,
    *,
    path_parameters: dict[str, Any] | None = None,
    connection_secrets: dict[str, str] | None = None,
) -> RequestTarget:
    """Bind each path segment once, sourcing route credentials from the connection."""
    route = route_for(operation_id)
    values = path_parameters or {}
    secrets = connection_secrets or {}
    secret_names = set(route["secret_path_parameters"])
    if values.keys() != set(route["path_parameters"]) - secret_names:
        raise ValueError("Path parameters do not match this operation")

    def encode(match: re.Match[str]) -> str:
        name = match[1]
        if name in secret_names:
            token = secrets.get(name, "")
            if not TOKEN.fullmatch(token):
                raise ValueError("Discord route credential is missing or invalid")
            return token
        value = values[name]
        if (
            isinstance(value, bool)
            or not isinstance(value, (str, int))
            or str(value) in {"", ".", ".."}
            or len(str(value)) > MAX_PATH_VALUE
        ):
            raise ValueError("Discord path parameter is invalid")
        return quote(str(value), safe="")

    return RequestTarget(
        method=route["method"],
        path=PLACEHOLDER.sub(encode, route["path"]),
        success_statuses=tuple(route["success_statuses"]),
    )
