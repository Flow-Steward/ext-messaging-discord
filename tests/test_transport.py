"""Exercise the Discord HTTP adapter without a network call."""

from io import BytesIO
from urllib.error import HTTPError

import pytest
from discord_fakes import Response, pinned
from runtime import transport


def send(**overrides):
    arguments = {
        "method": "POST",
        "path": "/channels/123/messages",
        "authorization": "Bot example.token",
        "user_agent": "Test",
        "success_statuses": (200,),
        "data": b"{}",
        "content_type": "application/json",
        "query": [],
        "audit_reason": "",
    }
    arguments.update(overrides)
    return transport.request_raw(**arguments)


def test_every_request_goes_through_the_sdk_pinned_opener(monkeypatch):
    opener = pinned(monkeypatch, Response(200, b'{"id":"1"}', {"Content-Type": "application/json"}))
    reply = send(timeout=7.5)
    assert reply.status == 200 and reply.raw == b'{"id":"1"}'
    [(request, timeout, purpose)] = opener.requests
    assert request.full_url == "https://discord.com/api/v10/channels/123/messages"
    assert timeout == 7.5
    assert purpose == "Discord API"


def test_raw_transport_encodes_query_and_audit_reason(monkeypatch):
    opener = pinned(
        monkeypatch,
        Response(201, b'{"id":"123"}', {"Content-Type": "application/json; charset=utf-8"}),
    )
    reply = send(
        path="/channels/123/invites",
        authorization="Bearer example.token",
        success_statuses=(201,),
        data=b"name=example",
        content_type="application/x-www-form-urlencoded",
        query=[("limit", "10")],
        audit_reason="Test / change",
    )
    assert (reply.status, reply.media_type, reply.raw) == (201, "application/json", b'{"id":"123"}')
    [(request, _, _)] = opener.requests
    assert request.full_url.endswith("/channels/123/invites?limit=10")
    assert request.get_header("Authorization") == "Bearer example.token"
    assert request.get_header("Content-type") == "application/x-www-form-urlencoded"
    assert request.get_header("X-audit-log-reason") == "Test%20%2F%20change"


def test_an_undocumented_success_status_is_reported_with_its_status(monkeypatch):
    pinned(monkeypatch, Response(201, b"{}"))
    with pytest.raises(transport.DiscordResponseError) as error:
        send(authorization=None)
    assert (error.value.status, error.value.reason) == (201, "unexpected_status")


def test_an_answer_up_to_8_mib_is_read_and_a_longer_one_is_not(monkeypatch):
    assert transport.MAX_RESPONSE == 8 * 1024 * 1024
    pinned(monkeypatch, Response(200, b"x" * transport.MAX_RESPONSE))
    assert len(send().raw) == transport.MAX_RESPONSE
    pinned(monkeypatch, Response(200, b"x" * (transport.MAX_RESPONSE + 1)))
    reply = send()
    assert (reply.raw, reply.unread) == (b"", "response_too_large")


def test_an_answer_cut_off_by_the_connection_keeps_its_status(monkeypatch):
    class Broken(Response):
        def read(self, size=-1):
            raise ConnectionResetError

    pinned(monkeypatch, Broken(200, b"", {"Content-Type": "application/json"}))
    reply = send()
    assert (reply.status, reply.unread) == (200, "incomplete_response")


def test_raw_transport_accepts_empty_success_without_content_type(monkeypatch):
    pinned(monkeypatch, Response(204, b""))
    reply = send(method="DELETE", data=None, content_type=None, success_statuses=(204,))
    assert (reply.status, reply.media_type, reply.raw) == (204, "", b"")


def test_rate_limit_headers_are_kept_and_nothing_else(monkeypatch):
    pinned(
        monkeypatch,
        Response(
            200,
            b"{}",
            {
                "X-RateLimit-Limit": "5",
                "X-RateLimit-Remaining": "4",
                "X-RateLimit-Reset-After": "1.5",
                "X-RateLimit-Bucket": "abcd1234",
                "Set-Cookie": "private",
            },
        ),
    )
    reply = send()
    assert set(reply.headers) == {
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset-After",
        "X-RateLimit-Bucket",
    }
    assert transport.rate_limit(reply.headers) == {
        "limit": 5,
        "remaining": 4,
        "reset_after": 1.5,
        "bucket": "abcd1234",
        "global": False,
    }


def test_rate_limit_only_exposes_structured_facts(monkeypatch):
    from email.message import Message

    headers = Message()
    headers["X-RateLimit-Global"] = "true"
    headers["Retry-After"] = "3"
    response = HTTPError(
        "https://discord.com/api/v10/channels/12/messages",
        429,
        "private upstream detail",
        headers,
        BytesIO(
            b'{"code": 20028, "retry_after": 2.5, "global": true, '
            b'"message": "private upstream detail"}'
        ),
    )
    opener = pinned(monkeypatch, response)
    with pytest.raises(transport.DiscordHTTPError) as result:
        send()
    assert result.value.status == 429
    assert result.value.code == 20028
    assert result.value.retry_after == 2.5
    assert result.value.global_limit is True
    assert "private upstream detail" not in str(result.value)
    assert len(opener.requests) == 1


def test_a_redirect_is_not_followed(monkeypatch):
    response = HTTPError("https://discord.com/api/v10/x", 302, "Found", None, BytesIO(b""))
    pinned(monkeypatch, response)
    with pytest.raises(transport.DiscordHTTPError) as result:
        send()
    assert result.value.status == 302


def test_invalid_paths_never_leave_the_process(monkeypatch):
    opener = pinned(monkeypatch, Response(200, b"{}"))
    for path in ("relative", "//evil.example/x", "/a?b", "/a#b"):
        with pytest.raises(ValueError):
            send(path=path)
    assert opener.requests == []
