"""Flow Steward adapters for the Discord REST read and write actions."""

from __future__ import annotations

import hashlib
from http.client import HTTPException
from typing import Any

from runtime.rest import execute, prepare
from runtime.transport import DiscordHTTPError

STATUS_ERRORS = {
    400: "upstream_validation_failed",
    401: "authentication_failed",
    403: "access_denied",
    404: "not_found",
    409: "upstream_validation_failed",
    429: "rate_limited",
}


def failure(code: str, *, uncertain: bool = False) -> dict[str, Any]:
    return {
        "ok": False,
        "result": {},
        "error_code": code,
        "error": code.replace("_", " "),
        "definitely_no_external_effect": not uncertain,
        "external_effect_status": "timeout_unknown" if uncertain else "failed",
    }


def dispatch_rest(
    action: dict[str, Any], inputs: dict[str, Any], context: Any, *, write: bool, user_agent: str
) -> dict[str, Any]:
    target = action.get("target")
    connection = target.get("connection") if isinstance(target, dict) else None
    connection_ref = inputs.get("connection_ref")
    if (
        not isinstance(connection, dict)
        or not isinstance(connection_ref, str)
        or not connection_ref
        or connection_ref != connection.get("connection_id")
    ):
        return failure("invalid_connection")
    operation = inputs.get("operation_id")
    test_mode = context.raw.get("test_mode", False)
    if not isinstance(operation, str) or not isinstance(test_mode, bool):
        return failure("invalid_payload")
    execution_id = context.step_execution_id
    if write and not (test_mode or execution_id):
        return failure("invalid_payload")
    envelope = inputs.get("body")
    body = envelope.get("data") if isinstance(envelope, dict) else None
    if operation == "create_message" and isinstance(body, dict) and execution_id:
        inputs = {
            **inputs,
            "body": {
                "data": {
                    **body,
                    "nonce": hashlib.sha256(execution_id.encode()).hexdigest()[:25],
                    "enforce_nonce": True,
                }
            },
        }
    try:
        prepared = prepare(operation, inputs=inputs, connection=connection, write=write)
    except (ValueError, TypeError, RecursionError):
        return failure("invalid_payload")
    if write and test_mode:
        return {"ok": True, "result": {"response": {}, "suppressed": True}}
    try:
        response = execute(prepared, user_agent=user_agent)
    except DiscordHTTPError as error:
        if error.status in STATUS_ERRORS:
            result = failure(STATUS_ERRORS[error.status])
            if error.code is not None:
                result["provider_error_code"] = error.code
            if error.retry_after is not None:
                result["retry_after_seconds"] = error.retry_after
            return result
        if 400 <= error.status < 500 and error.status != 408:
            return failure("upstream_validation_failed")
        return failure("timeout_unknown" if write else "provider_unavailable", uncertain=write)
    except (OSError, HTTPException, ValueError, RecursionError):
        return failure("timeout_unknown" if write else "provider_unavailable", uncertain=write)
    result = {"ok": True, "result": {"response": response, "suppressed": False}}
    if write:
        result["external_effect_status"] = "succeeded"
    return result
