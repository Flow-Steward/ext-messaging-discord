"""Bounded transport for Discord REST endpoints."""

from __future__ import annotations

import json
import math
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

API = "https://discord.com/api/v10"
MAX_RESPONSE = 256_000
MAX_ERROR = 8_192


class NoRedirect(HTTPRedirectHandler):
    """Credentials stay on the fixed Discord API origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class DiscordHTTPError(Exception):
    """Structured public facts from an HTTP failure without raw provider text."""

    def __init__(self, status: int, code: int | None, retry_after: float | None) -> None:
        super().__init__(status)
        self.status = status
        self.code = code
        self.retry_after = retry_after


def _rate_delay(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        delay = float(value)
    except (OverflowError, ValueError):
        return None
    return delay if math.isfinite(delay) and delay >= 0 else None


def _http_error(error: HTTPError) -> DiscordHTTPError:
    with error:
        retry_header = error.headers.get("Retry-After") if error.headers else None
        try:
            raw = error.read(MAX_ERROR + 1)
            parsed = json.loads(raw) if len(raw) <= MAX_ERROR else None
        except (OSError, ValueError, RecursionError):
            parsed = None
    data = parsed if isinstance(parsed, dict) else {}
    raw_code = data.get("code")
    code = raw_code if type(raw_code) is int else None
    delay = None
    if error.code == 429:
        delay = _rate_delay(data.get("retry_after"))
        if delay is None:
            delay = _rate_delay(retry_header)
    return DiscordHTTPError(error.code, code, delay)


def request_json(
    *,
    method: str,
    path: str,
    token: str,
    user_agent: str,
    success_statuses: tuple[int, ...],
    body: dict[str, Any] | None = None,
    query: dict[str, str | int] | None = None,
) -> dict[str, Any] | list[Any] | None:
    """Perform exactly one request. The caller supplies a registered path and statuses."""
    if not path.startswith("/") or path.startswith("//") or any(c in path for c in "?#"):
        raise ValueError("Invalid Discord API path")
    query_string = f"?{urlencode(query)}" if query else ""
    request = Request(  # nosec B310
        f"{API}{path}{query_string}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": user_agent,
        },
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=10) as response:
            if response.status not in success_statuses:
                raise ValueError("Unexpected Discord response status")
            if response.status == 204:
                return None
            raw = response.read(MAX_RESPONSE + 1)
    except HTTPError as error:
        raise _http_error(error) from None
    if len(raw) > MAX_RESPONSE:
        raise ValueError("Discord response exceeded its limit")
    parsed = json.loads(raw)
    if not isinstance(parsed, (dict, list)):
        raise ValueError("Discord response was not an object or array")
    return parsed


def request_raw(
    *,
    method: str,
    path: str,
    authorization: str | None,
    user_agent: str,
    success_statuses: tuple[int, ...],
    data: bytes | None,
    content_type: str | None,
    query: list[tuple[str, str]],
    audit_reason: str,
) -> tuple[int, str, bytes]:
    """Send a prepared registry request once and bound its response."""
    from urllib.parse import quote

    if not path.startswith("/") or path.startswith("//") or any(c in path for c in "?#"):
        raise ValueError("Invalid Discord API path")
    headers = {"User-Agent": user_agent}
    if authorization:
        headers["Authorization"] = authorization
    if content_type:
        headers["Content-Type"] = content_type
    if audit_reason:
        headers["X-Audit-Log-Reason"] = quote(audit_reason, safe="")
    suffix = f"?{urlencode(query)}" if query else ""
    request = Request(f"{API}{path}{suffix}", data=data, headers=headers, method=method)  # nosec B310
    try:
        with build_opener(NoRedirect()).open(request, timeout=10) as response:
            if response.status not in success_statuses:
                raise ValueError("Unexpected Discord response status")
            media_type = response.headers.get_content_type()
            raw = response.read(MAX_RESPONSE + 1) if response.status != 204 else b""
            if len(raw) > MAX_RESPONSE:
                raise ValueError("Discord response exceeded its limit")
            return response.status, media_type, raw
    except HTTPError as error:
        raise _http_error(error) from None
