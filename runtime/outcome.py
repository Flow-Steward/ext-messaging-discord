"""What one Discord answer means for a read and for a write.

``read_data`` and ``write_data`` are the only two places that decide it. The status has
already been checked by the transport against the operation's documented success
statuses; ``route["response_media_types"]`` holds the media types Discord documents for
each of them.

A read never returns an answer it could not read as if it were empty:

- an answer larger than the 8 MiB the extension reads → ``response_too_large``;
- an undocumented 2xx status, an answer cut off by the connection, an empty body where
  Discord documents one, a Content-Type Discord does not document for the status, a
  body that does not parse, or one nested too deeply → ``invalid_response``.

Both are failures without an external effect.

A write follows table T, the first rule that applies decides:

- T1. A 2xx status the operation does not document: ``timeout_unknown`` (decided by
  the transport's ``unexpected_status``).
- T2. Discord documents JSON for the status and the Content-Type is present and not
  JSON: ``timeout_unknown``, whatever happened to the body.
- T4. The body was not read in full (larger than 8 MiB, cut off): the write is
  confirmed by its status: success, ``data: null`` and a warning.
- An empty body: success without data.
- T3. JSON is documented and the body does not start with ``{`` or ``[`` or does not
  parse: ``timeout_unknown``.
- T4. The body nests deeper than the output allows: success, ``data: null``, a warning.
- T6. Otherwise success. A body Discord does not document as JSON is returned as text
  with a warning when it is not JSON.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from runtime.nesting import MAX_ANSWER_DEPTH, too_deep
from runtime.rest import redact_response
from runtime.files import size_text
from runtime.transport import MAX_RESPONSE, Reply

JSON = "application/json"
DECODED = {JSON, "text/csv", "image/png"}
MAX_TEXT = 20_000
_JSON_STARTS = (b"{", b"[")


class Unusable(Exception):
    """The answer cannot be returned: ``code`` is the step's error code."""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


def documented_types(route: dict[str, Any], status: int) -> list[str]:
    return list(route.get("response_media_types", {}).get(str(status), []))


def _json(raw: bytes) -> Any:
    if too_deep(raw):
        raise RecursionError
    return json.loads(raw)


def _decode(kind: str, raw: bytes, credentials: tuple[str, ...]) -> Any:
    if kind == JSON:
        return redact_response(_json(raw), credentials)
    if kind == "text/csv":
        return redact_response(raw.decode("utf-8", errors="replace"), credentials)
    return {"base64": base64.b64encode(raw).decode("ascii")}


def read_data(reply: Reply, route: dict[str, Any], credentials: tuple[str, ...]) -> Any:
    """The data of a read's answer; raises ``Unusable`` when it cannot be returned."""
    if reply.unread == "response_too_large":
        raise Unusable(
            "response_too_large", f"Discord's answer is larger than {size_text(MAX_RESPONSE)}"
        )
    if reply.unread is not None:
        raise Unusable("invalid_response", "Discord's answer was cut off")
    documented = documented_types(route, reply.status)
    if not reply.raw:
        if documented:
            raise Unusable("invalid_response", "Discord's answer has no body")
        return None
    kind = reply.media_type
    if documented:
        if kind and kind not in documented:
            raise Unusable("invalid_response", "Discord's answer has an undocumented type")
        kind = kind or (documented[0] if len(documented) == 1 else "")
    if kind not in DECODED:
        raise Unusable("invalid_response", "Discord's answer has an unexpected type")
    try:
        return _decode(kind, reply.raw, credentials)
    except (ValueError, RecursionError):
        raise Unusable("invalid_response", "Discord's answer could not be read") from None


def write_data(
    reply: Reply, route: dict[str, Any], credentials: tuple[str, ...]
) -> tuple[Any, list[str]]:
    """The data and warnings of a confirmed write; raises ``Unusable`` with
    ``timeout_unknown`` when the outcome is not known (T2, T3)."""
    shown = f"HTTP {reply.status}"
    documented = documented_types(route, reply.status)
    promised = JSON in documented
    kind = reply.media_type
    if promised and kind and kind != JSON:  # T2
        raise Unusable("timeout_unknown", "Discord confirmed the status but not with JSON")
    if reply.unread is not None:  # T4
        reason = (
            f"larger than {size_text(MAX_RESPONSE)}"
            if reply.unread == "response_too_large"
            else "cut off"
        )
        return None, [
            f"Discord confirmed the change ({shown}) but its answer was not read ({reason}); "
            "data is null"
        ]
    if not reply.raw:
        return None, []
    if promised:
        start = reply.raw.lstrip(b"\xef\xbb\xbf \t\r\n")[:1]
        if start not in _JSON_STARTS:  # T3
            raise Unusable("timeout_unknown", "Discord's answer is not the documented JSON")
        if too_deep(reply.raw):  # T4
            return None, [
                f"Discord confirmed the change ({shown}) but its answer nests deeper than "
                f"{MAX_ANSWER_DEPTH} levels; data is null"
            ]
        try:
            return redact_response(json.loads(reply.raw), credentials), []
        except (ValueError, RecursionError):  # T3
            raise Unusable(
                "timeout_unknown", "Discord's answer is not the documented JSON"
            ) from None
    if kind in DECODED:
        try:
            return _decode(kind, reply.raw, credentials), []
        except RecursionError:
            return None, [
                f"Discord confirmed the change ({shown}) but its answer nests deeper than "
                f"{MAX_ANSWER_DEPTH} levels; data is null"
            ]
        except ValueError:
            pass
    text = redact_response(reply.raw.decode("utf-8", errors="replace"), credentials)
    return text[:MAX_TEXT], [
        f"Discord confirmed the change ({shown}) but its answer is not JSON; it is returned as text"
    ]
