"""Bounded transport for Discord REST endpoints.

Every request goes through the SDK's ``open_pinned_url``: the API host is resolved
once, the connection is pinned to a public address and redirects are not followed,
so credentials stay on the fixed Discord API origin. Each call sends exactly one
request; nothing here retries.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from http.client import HTTPException
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request

from flowsteward_extension_sdk import open_pinned_url

from runtime.files import MIB

API = "https://discord.com/api/v10"
#: One Discord answer is read up to 8 MiB; a longer one is not read.
MAX_RESPONSE = 8 * MIB
MAX_ERROR = 8_192
#: The longest rate limit header value kept (our bound; Discord's are short).
MAX_HEADER_VALUE = 128
DEFAULT_TIMEOUT_SECONDS = 10.0
CHUNK = 256 * 1024
PURPOSE = "Discord API"

#: Discord's rate limit headers (developers/topics/rate-limits.mdx).
RATE_LIMIT_HEADERS = (
    "X-RateLimit-Limit",
    "X-RateLimit-Remaining",
    "X-RateLimit-Reset-After",
    "X-RateLimit-Bucket",
    "X-RateLimit-Global",
    "X-RateLimit-Scope",
)


@dataclass(frozen=True)
class Reply:
    """A documented success status and what could be read of its body."""

    status: int
    media_type: str
    raw: bytes = field(repr=False)
    headers: Mapping[str, str] = field(default_factory=dict)
    #: ``response_too_large`` or ``incomplete_response`` when the body was not read.
    unread: str | None = None


class DiscordHTTPError(Exception):
    """Structured public facts from an HTTP failure without raw provider text."""

    def __init__(
        self,
        status: int,
        code: int | None,
        retry_after: float | None,
        *,
        headers: Mapping[str, str] | None = None,
        global_limit: bool | None = None,
    ) -> None:
        super().__init__(status)
        self.status = status
        self.code = code
        self.retry_after = retry_after
        self.headers = dict(headers or {})
        self.global_limit = global_limit


class DiscordResponseError(Exception):
    """Discord answered with a 2xx status the operation does not document."""

    def __init__(self, status: int, reason: str, headers: Mapping[str, str] | None = None) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.headers = dict(headers or {})


def _rate_delay(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        delay = float(value)
    except (OverflowError, ValueError):
        return None
    return delay if math.isfinite(delay) and delay >= 0 else None


def kept_headers(headers: Any) -> dict[str, str]:
    """Only Discord's rate limit headers, with bounded values."""
    kept: dict[str, str] = {}
    if headers is None:
        return kept
    for name in RATE_LIMIT_HEADERS:
        try:
            value = headers.get(name)
        except AttributeError:
            return kept
        if isinstance(value, str) and value.strip():
            kept[name] = value.strip()[:MAX_HEADER_VALUE]
    return kept


def media_type(headers: Any) -> str:
    """The Content-Type without parameters, or "" when the answer has none."""
    try:
        value = headers.get("Content-Type") if headers is not None else None
    except AttributeError:
        return ""
    if not isinstance(value, str):
        return ""
    return value.split(";", 1)[0].strip().lower()


def _http_error(error: HTTPError) -> DiscordHTTPError:
    with error:
        headers = error.headers
        retry_header = headers.get("Retry-After") if headers else None
        try:
            raw = error.read(MAX_ERROR + 1)
            parsed = json.loads(raw) if len(raw) <= MAX_ERROR else None
        except (OSError, HTTPException, ValueError, RecursionError):
            parsed = None
    data = parsed if isinstance(parsed, dict) else {}
    raw_code = data.get("code")
    code = raw_code if type(raw_code) is int else None
    delay = None
    global_limit = None
    kept = kept_headers(headers)
    if error.code == 429:
        delay = _rate_delay(data.get("retry_after"))
        if delay is None:
            delay = _rate_delay(retry_header)
        body_global = data.get("global")
        global_limit = (body_global is True) or kept.get("X-RateLimit-Global", "").lower() == "true"
    return DiscordHTTPError(error.code, code, delay, headers=kept, global_limit=global_limit)


def _read(response: Any) -> tuple[bytes, str | None]:
    buffer = bytearray()
    try:
        while len(buffer) <= MAX_RESPONSE:
            chunk = response.read(min(CHUNK, MAX_RESPONSE + 1 - len(buffer)))
            if not chunk:
                # http.client ends a read short of Content-Length without an error when
                # the connection closes; the bytes still owed mean the answer was cut off.
                owed = getattr(response, "length", None)
                if isinstance(owed, int) and not isinstance(owed, bool) and owed > 0:
                    return b"", "incomplete_response"
                break
            buffer.extend(chunk)
    except (OSError, HTTPException):
        return b"", "incomplete_response"
    if len(buffer) > MAX_RESPONSE:
        return b"", "response_too_large"
    return bytes(buffer), None


class SizedBody(Protocol):
    """A body sent piece by piece whose length is known before it is sent."""

    def __iter__(self) -> Iterator[bytes]: ...

    def __len__(self) -> int: ...


def request_raw(
    *,
    method: str,
    path: str,
    authorization: str | None,
    user_agent: str,
    success_statuses: tuple[int, ...],
    data: bytes | SizedBody | None,
    content_type: str | None,
    query: list[tuple[str, str]],
    audit_reason: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Reply:
    """Send a prepared registry request once and bound its response."""
    if not path.startswith("/") or path.startswith("//") or any(c in path for c in "?#"):
        raise ValueError("Invalid Discord API path")
    headers = {"User-Agent": user_agent}
    if authorization:
        headers["Authorization"] = authorization
    if content_type:
        headers["Content-Type"] = content_type
    if data is not None and not isinstance(data, bytes):
        # A body sent piece by piece (a multipart body): its length is sent first.
        headers["Content-Length"] = str(len(data))
    if audit_reason:
        headers["X-Audit-Log-Reason"] = quote(audit_reason, safe="")
    suffix = f"?{urlencode(query)}" if query else ""
    request = Request(f"{API}{path}{suffix}", data=data, headers=headers, method=method)
    try:
        with open_pinned_url(request, timeout_seconds=timeout, purpose=PURPOSE) as response:
            status = int(getattr(response, "status", 0) or 0)
            response_headers = getattr(response, "headers", None)
            kept = kept_headers(response_headers)
            if status not in success_statuses:
                raise DiscordResponseError(status, "unexpected_status", kept)
            kind = media_type(response_headers)
            if status == 204:
                return Reply(status, kind, b"", kept)
            raw, unread = _read(response)
            return Reply(status, kind, raw, kept, unread)
    except HTTPError as error:
        raise _http_error(error) from None


def rate_limit(headers: Mapping[str, str], *, global_limit: bool | None = None) -> dict[str, Any]:
    """The ``rate_limit`` output: Discord's limit facts from the response headers."""

    def integer(name: str) -> int | None:
        value = headers.get(name)
        return int(value) if isinstance(value, str) and value.isdigit() else None

    reset_after = _rate_delay(headers.get("X-RateLimit-Reset-After"))
    bucket = headers.get("X-RateLimit-Bucket")
    is_global = headers.get("X-RateLimit-Global", "").lower() == "true" or bool(global_limit)
    return {
        "limit": integer("X-RateLimit-Limit"),
        "remaining": integer("X-RateLimit-Remaining"),
        "reset_after": reset_after,
        "bucket": bucket if isinstance(bucket, str) else None,
        "global": is_global,
    }
