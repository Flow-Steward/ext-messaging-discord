"""Flow Steward adapters for the Discord REST read and write actions."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Iterable
from dataclasses import replace
from http.client import HTTPException
from typing import Any

from flowsteward_extension_sdk import PinnedPeerError, stream_artifact_bytes

from runtime import budget
from runtime.outcome import Unusable, read_data, write_data
from runtime.paging import (
    PAGING,
    PageShapeError,
    Paging,
    merge,
    next_cursor,
    page_complete,
    page_items,
)
from runtime.files import READ_CHUNK_BYTES
from runtime.rest import Prepared, execute, prepare
from runtime.routes import route_for
from runtime.transport import (
    DEFAULT_TIMEOUT_SECONDS,
    DiscordHTTPError,
    DiscordResponseError,
    Reply,
    rate_limit,
)

STATUS_ERRORS = {
    400: "upstream_validation_failed",
    401: "authentication_failed",
    403: "access_denied",
    404: "not_found",
    409: "upstream_validation_failed",
    429: "rate_limited",
}
#: The entrypoint has 30 s; no page of a list starts after this many seconds, and every
#: page request ends by ``PAGE_WINDOW_END_SECONDS``.
PAGE_DEADLINE_SECONDS = 15.0
PAGE_WINDOW_END_SECONDS = 25.0
MIN_PAGE_WINDOW_SECONDS = 2.0
#: Create Message: nonce "can be used to verify a message was sent (up to 25 characters)"
#: (discord-api-docs, message.mdx).
NONCE_LENGTH = 25
ARTIFACT_TIMEOUT_SECONDS = 20.0
TEST_RUN_WARNING = "Test run: the inputs were checked and nothing was sent to Discord"


def failure(
    code: str, *, uncertain: bool = False, result: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "ok": False,
        "result": result or {},
        "error_code": code,
        "error": code.replace("_", " "),
        "definitely_no_external_effect": not uncertain,
        "external_effect_status": "timeout_unknown" if uncertain else "failed",
    }


def test_run(result: dict[str, Any]) -> dict[str, Any]:
    """A write in a test run: inputs checked, nothing sent. "failed" together with
    definitely-no-effect is the pair the host accepts for "no external effect"."""
    return {
        "ok": True,
        "result": {
            **result,
            "suppressed": True,
            "processing": None,
            "rate_limit": None,
            "warnings": [TEST_RUN_WARNING],
        },
        "external_effect_status": "failed",
        "definitely_no_external_effect": True,
    }


def http_failure(error: DiscordHTTPError, *, write: bool) -> dict[str, Any]:
    limits = rate_limit(error.headers, global_limit=error.global_limit)
    code = STATUS_ERRORS.get(error.status)
    if code is None:
        if write:
            return failure("timeout_unknown", uncertain=True, result={"rate_limit": limits})
        return failure("provider_unavailable", result={"rate_limit": limits})
    result = failure(code, result={"rate_limit": limits})
    if error.code is not None:
        result["provider_error_code"] = error.code
    if error.status == 429:
        if error.retry_after is not None:
            result["retry_after_seconds"] = error.retry_after
        result["rate_limit_global"] = bool(error.global_limit)
    return result


def connection_of(action: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any] | None:
    target = action.get("target")
    connection = target.get("connection") if isinstance(target, dict) else None
    connection_ref = inputs.get("connection_ref")
    if (
        not isinstance(connection, dict)
        or not isinstance(connection_ref, str)
        or not connection_ref
        or connection_ref != connection.get("connection_id")
    ):
        return None
    return connection


def artifact_reader(action: dict[str, Any], *, test_mode: bool) -> Callable[[str], Iterable[bytes]]:
    """A workflow file by its handle, streamed from storage in pieces."""
    if test_mode:
        # A test run checks the inputs; the file is not read because nothing is sent.
        return lambda handle: iter(())
    artifacts = action.get("artifacts")
    payload = {"artifacts": artifacts if isinstance(artifacts, dict) else {}}
    return lambda handle: stream_artifact_bytes(
        payload,
        artifact_id=handle,
        chunk_size=READ_CHUNK_BYTES,
        timeout_seconds=ARTIFACT_TIMEOUT_SECONDS,
    )


def dispatch_rest(
    action: dict[str, Any],
    inputs: dict[str, Any],
    context: Any,
    *,
    write: bool,
    user_agent: str,
    all_pages: bool = False,
    clock: Callable[[], float] | None = None,
) -> dict[str, Any]:
    connection = connection_of(action, inputs)
    if connection is None:
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
                    "nonce": hashlib.sha256(execution_id.encode()).hexdigest()[:NONCE_LENGTH],
                    "enforce_nonce": True,
                }
            },
        }
    try:
        prepared = prepare(
            operation,
            inputs=inputs,
            connection=connection,
            write=write,
            read_artifact=artifact_reader(action, test_mode=test_mode),
        )
    except (ValueError, TypeError, RecursionError):
        return failure("invalid_payload")
    route = route_for(operation)
    if route.get("provider_disabled"):
        return failure("operation_disabled")
    if write and test_mode:
        return test_run({"response": None})
    paging = None if write else PAGING.get(operation)
    if all_pages:
        if paging is None:
            return failure("invalid_payload")
        return read_all_pages(
            prepared, route, paging, user_agent=user_agent, clock=clock or time.monotonic
        )
    try:
        reply = execute(prepared, user_agent=user_agent)
    except Exception as error:  # noqa: BLE001 - mapped to the documented outcomes
        return transport_failure(error, write=write)
    if write:
        return write_result(reply, route, prepared)
    return read_result(reply, route, prepared, paging)


def transport_failure(error: Exception, *, write: bool) -> dict[str, Any]:
    if isinstance(error, DiscordHTTPError):
        return http_failure(error, write=write)
    limits = {"rate_limit": rate_limit(getattr(error, "headers", {}) or {})}
    if isinstance(error, DiscordResponseError):
        # T1: a 2xx status the operation does not document.
        if write:
            return failure("timeout_unknown", uncertain=True, result=limits)
        return failure("invalid_response", result=limits)
    if isinstance(error, PinnedPeerError):
        # Raised while resolving and pinning the host, before anything is sent.
        return failure("provider_unavailable")
    if isinstance(error, (OSError, HTTPException, ValueError, RecursionError)):
        if write:
            return failure("timeout_unknown", uncertain=True)
        return failure("provider_unavailable")
    raise error


def _response(reply: Reply, data: Any) -> dict[str, Any]:
    return {"status": reply.status, "media_type": reply.media_type, "data": data}


def write_result(reply: Reply, route: dict[str, Any], prepared: Prepared) -> dict[str, Any]:
    limits = rate_limit(reply.headers)
    try:
        data, warnings = write_data(reply, route, prepared.credentials)
    except Unusable:
        return failure("timeout_unknown", uncertain=True, result={"rate_limit": limits})
    result: dict[str, Any] = {
        "response": _response(reply, data),
        "suppressed": False,
        "processing": "completed",
        "rate_limit": limits,
        "warnings": warnings,
    }
    envelope = {"ok": True, "result": result, "external_effect_status": "succeeded"}
    if not budget.fits(envelope, room=budget.WARNING_ROOM):
        result["response"]["data"] = None
        warnings.append(
            f"Discord confirmed the change (HTTP {reply.status}) but its answer is too large "
            "for one step output; data is null"
        )
    return envelope


def _single_page_cursor(
    paging: Paging, prepared: Prepared, data: Any
) -> tuple[str | None, bool | None]:
    given = [name for name, _ in prepared.query if name in {"before", "after", "around"}]
    if "around" in given:
        return None, None
    direction = given[0] if given else paging.directions[0] if len(paging.directions) == 1 else None
    if direction is None:
        return None, None
    try:
        items = page_items(paging, data)
        done = page_complete(paging, data, items)
        return (None if done else next_cursor(paging, items, direction)), done
    except PageShapeError:
        return None, None


def read_result(
    reply: Reply, route: dict[str, Any], prepared: Prepared, paging: Paging | None
) -> dict[str, Any]:
    limits = rate_limit(reply.headers)
    try:
        data = read_data(reply, route, prepared.credentials)
    except Unusable as error:
        return failure(error.code, result={"rate_limit": limits})
    result: dict[str, Any] = {
        "response": _response(reply, data),
        "suppressed": False,
        "rate_limit": limits,
        "warnings": [],
    }
    if paging is not None:
        cursor, done = _single_page_cursor(paging, prepared, data)
        result.update(next_cursor=cursor, complete=done, pages=1)
    envelope = {"ok": True, "result": result}
    if not budget.fits(envelope):
        return failure("response_too_large", result={"rate_limit": limits})
    return envelope


def _with_cursor(
    query: list[tuple[str, str]], direction: str, cursor: str | None, limit: int
) -> list[tuple[str, str]]:
    kept = [(name, value) for name, value in query if name not in {"before", "after", "limit"}]
    if cursor is not None:
        kept.append((direction, cursor))
    kept.append(("limit", str(limit)))
    return kept


def read_all_pages(
    prepared: Prepared,
    route: dict[str, Any],
    paging: Paging,
    *,
    user_agent: str,
    clock: Callable[[], float],
) -> dict[str, Any]:
    """Every page of a list, exactly continued by its cursor, inside the step's time
    and output; a list that stops early says where to go on (next_cursor, complete)."""
    query = dict(prepared.query)
    if "around" in query or ("before" in query and "after" in query):
        return failure("invalid_payload")
    given = [name for name in ("before", "after") if name in query]
    direction = given[0] if given else paging.directions[0]
    if direction not in paging.directions:
        return failure("invalid_payload")
    # With no cursor, "after" starts at the first id (0); "before" starts at the newest.
    cursor = query.get(direction, "0" if direction == "after" else None)
    limit = int(query["limit"]) if "limit" in query else paging.max_limit
    started = clock()
    pages: list[Any] = []
    last: Reply | None = None
    limits: dict[str, Any] | None = None
    stopped: str | None = None
    complete = False
    while True:
        elapsed = clock() - started
        if pages and elapsed > PAGE_DEADLINE_SECONDS:
            stopped = "the step's time is used up"
            break
        timeout = max(
            MIN_PAGE_WINDOW_SECONDS, min(DEFAULT_TIMEOUT_SECONDS, PAGE_WINDOW_END_SECONDS - elapsed)
        )
        page_request = replace(
            prepared, query=_with_cursor(prepared.query, direction, cursor, limit)
        )
        try:
            reply = execute(page_request, user_agent=user_agent, timeout=timeout)
        except DiscordHTTPError as error:
            if pages and error.status == 429:
                limits = rate_limit(error.headers, global_limit=error.global_limit)
                wait = "" if error.retry_after is None else f" (retry after {error.retry_after} s)"
                stopped = f"Discord rate limited the next request{wait}"
                break
            return http_failure(error, write=False)
        except (OSError, HTTPException) as error:
            if pages:
                stopped = "the next page could not be read"
                break
            return transport_failure(error, write=False)
        except Exception as error:  # noqa: BLE001 - mapped to the documented outcomes
            return transport_failure(error, write=False)
        limits = rate_limit(reply.headers)
        try:
            data = read_data(reply, route, prepared.credentials)
            items = page_items(paging, data)
            done = page_complete(paging, data, items)
            following = next_cursor(paging, items, direction)
        except Unusable as error:
            return failure(error.code, result={"rate_limit": limits})
        except PageShapeError:
            return failure("invalid_response", result={"rate_limit": limits})
        if not done and following == cursor:
            # The cursor would not move: going on could only repeat this page.
            return failure("invalid_response", result={"rate_limit": limits})
        candidate = _all_pages_envelope(
            reply, merge(paging, [*pages, data]), limits, [], following, done, len(pages) + 1
        )
        if not budget.fits(candidate, room=0 if done else budget.WARNING_ROOM):
            if not pages:
                return failure("response_too_large", result={"rate_limit": limits})
            stopped = "the next page does not fit in one step output"
            break
        pages.append(data)
        last = reply
        cursor = following
        if done:
            complete = True
            break
    if last is None:  # pragma: no cover - the loop takes a page or returns
        return failure("invalid_response")
    warnings = []
    if stopped is not None:
        warnings.append(
            f"Stopped after {len(pages)} pages: {stopped}. The list is not complete; "
            f"continue with {direction}={cursor}"
        )
    return _all_pages_envelope(
        last,
        merge(paging, pages),
        limits,
        warnings,
        None if complete else cursor,
        complete,
        len(pages),
    )


def _all_pages_envelope(
    reply: Reply,
    data: Any,
    limits: dict[str, Any] | None,
    warnings: list[str],
    cursor: str | None,
    complete: bool,
    pages: int,
) -> dict[str, Any]:
    return {
        "ok": True,
        "result": {
            "response": _response(reply, data),
            "suppressed": False,
            "rate_limit": limits,
            "warnings": warnings,
            "next_cursor": None if complete else cursor,
            "complete": complete,
            "pages": pages,
        },
    }
