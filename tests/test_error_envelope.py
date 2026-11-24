"""Every error the extension returns is the host's public error envelope.

The host (core/infrastructure/extension_runtime/extension_runtime_invocation.py,
_is_structured_extension_error) counts a failure toward quarantine unless the envelope
carries error_code, error and an errors list whose first entry repeats them.
"""

from __future__ import annotations

import pytest

from runtime import rest_action

CODES = [
    "invalid_payload",
    "invalid_connection",
    "invalid_response",
    "not_found",
    "access_denied",
    "authentication_failed",
    "rate_limited",
    "upstream_validation_failed",
    "operation_disabled",
    "provider_unavailable",
    "timeout_unknown",
]


def host_accepts(response: dict) -> bool:
    if response.get("ok") is not False:
        return False
    code = str(response.get("error_code") or "").strip()
    message = str(response.get("error") or "").strip()
    errors = response.get("errors")
    if not code or not message or not isinstance(errors, list) or not errors:
        return False
    if not all(
        isinstance(e, dict)
        and str(e.get("code") or "").strip()
        and str(e.get("message") or "").strip()
        for e in errors
    ):
        return False
    return errors[0]["code"] == code and errors[0]["message"] == message


@pytest.mark.parametrize("code", CODES)
def test_every_error_is_the_hosts_public_envelope(code):
    for uncertain in (False, True):
        response = rest_action.failure(code, uncertain=uncertain)
        assert host_accepts(response), response
        assert response["warnings"] == []


def test_the_entrypoint_failure_is_the_same_envelope():
    import main

    assert host_accepts(main._failure("invalid_payload"))
