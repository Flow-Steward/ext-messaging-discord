"""Discord extension subprocess entrypoint."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from flowsteward_extension_sdk import connection_from_payload, runtime_context_from_payload

API = "https://discord.com/api/v10"
MAX_INPUT = 32_768
MAX_RESPONSE = 256_000
SNOWFLAKE = re.compile(r"[0-9]{1,20}")
TOKEN = re.compile(r"[A-Za-z0-9._-]{1,512}")
STATUS_ERRORS = {
    400: "invalid_payload",
    401: "authentication_failed",
    403: "access_denied",
    404: "not_found",
    429: "rate_limited",
}


class NoRedirect(HTTPRedirectHandler):
    """A bot credential may only be sent to the fixed Discord API origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _failure(code: str, *, uncertain: bool = False) -> dict[str, Any]:
    return {
        "ok": False,
        "result": {},
        "error_code": code,
        "error": code.replace("_", " "),
        "definitely_no_external_effect": not uncertain,
        "external_effect_status": "unknown" if uncertain else "failed",
    }


def _request(path: str, token: str, body: dict | None = None) -> dict:
    request = Request(  # nosec B310 -- fixed HTTPS origin and validated path segments
        f"{API}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (https://github.com/Flow-Steward, 0.1.0)",
        },
    )
    with build_opener(NoRedirect()).open(request, timeout=10) as response:
        if response.status != 200:
            raise ValueError("Unexpected Discord response status")
        raw = response.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise ValueError("Discord response exceeded its limit")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Discord response was not an object")
    return parsed


def dispatch(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        context = runtime_context_from_payload(payload)
    except ValueError:
        return _failure("invalid_payload")
    action = payload.get("action")
    if payload.get("mode") != "action" or not isinstance(action, dict):
        return _failure("invalid_payload")
    operation = action.get("action_id") or action.get("operation_id")
    inputs = action.get("input", {})
    if operation not in ("test_connection", "send_message") or not isinstance(inputs, dict):
        return _failure("invalid_payload")

    write = operation == "send_message"
    allowed = {"connection_ref", "channel_id", "content"} if write else {"connection_ref"}
    if inputs.keys() - allowed:
        return _failure("invalid_payload")
    channel_id, content = inputs.get("channel_id"), inputs.get("content")
    if write and not (
        isinstance(channel_id, str)
        and SNOWFLAKE.fullmatch(channel_id)
        and isinstance(content, str)
        and content.strip()
        and len(content.encode("utf-16-le", errors="surrogatepass")) <= 4000
    ):
        return _failure("invalid_payload")
    test_mode = context.raw.get("test_mode", False)
    if not isinstance(test_mode, bool):
        return _failure("invalid_payload")
    if write and test_mode:
        return {
            "ok": True,
            "result": {"message_id": "", "channel_id": channel_id, "suppressed": True},
        }

    connection = connection_from_payload(payload)
    connection_ref = inputs.get("connection_ref")
    if connection is None or (connection_ref and connection.connection_id != connection_ref):
        return _failure("invalid_connection")
    if connection.connection_type and connection.connection_type != "discord_bot":
        return _failure("invalid_connection")
    token = connection.secrets.get("bot_token")
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        return _failure("invalid_connection")

    body: dict[str, Any] | None = None
    path = "/users/@me"
    if write:
        path = f"/channels/{channel_id}/messages"
        body = {"content": content, "allowed_mentions": {"parse": []}}
        if context.step_execution_id:
            body.update(
                nonce=hashlib.sha256(context.step_execution_id.encode()).hexdigest()[:25],
                enforce_nonce=True,
            )
    try:
        response = _request(path, token, body)
        provider_id = response.get("id")
        if not isinstance(provider_id, str) or not SNOWFLAKE.fullmatch(provider_id):
            raise ValueError("Discord response did not contain an ID")
    except HTTPError as exc:
        exc.close()
        if exc.code in STATUS_ERRORS:
            return _failure(STATUS_ERRORS[exc.code])
        return _failure("timeout_unknown" if write else "provider_unavailable", uncertain=write)
    except (URLError, OSError, ValueError):
        return _failure("timeout_unknown" if write else "provider_unavailable", uncertain=write)

    if write:
        return {
            "ok": True,
            "result": {"message_id": provider_id, "channel_id": channel_id, "suppressed": False},
            "external_effect_status": "applied",
        }
    return {"ok": True, "result": {"bot_id": provider_id}}


def main() -> int:
    raw = sys.stdin.buffer.read(MAX_INPUT + 1)
    try:
        payload = json.loads(raw) if len(raw) <= MAX_INPUT else None
        response = dispatch(payload) if isinstance(payload, dict) else _failure("invalid_payload")
    except (UnicodeError, ValueError, RecursionError):
        response = _failure("invalid_payload")
    print(json.dumps(response))
    return 0 if response["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
