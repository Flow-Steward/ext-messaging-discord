"""Exercise the Discord HTTP adapter without a network call."""

from io import BytesIO
from urllib.error import HTTPError

import pytest
from runtime import transport


class Response(BytesIO):
    def __init__(self, status: int, body: bytes):
        super().__init__(body)
        self.status = status


class Opener:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def open(self, request, *, timeout):
        self.requests.append((request, timeout))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.mark.parametrize(
    ("status", "raw", "expected"),
    [
        (200, b'[{"id":"11"}]', [{"id": "11"}]),
        (201, b'{"id":"11"}', {"id": "11"}),
        (204, b"", None),
    ],
)
def test_registered_statuses_and_response_shapes(monkeypatch, status, raw, expected):
    opener = Opener(Response(status, raw))

    def build_opener(handler):
        assert isinstance(handler, transport.NoRedirect)
        assert handler.redirect_request(None, None, 302, None, None, "https://example.test") is None
        return opener

    monkeypatch.setattr(transport, "build_opener", build_opener)
    assert (
        transport.request_json(
            method="GET",
            path="/channels/12/messages",
            token="example.token",
            user_agent="DiscordBot Test",
            success_statuses=(status,),
            query={"after": "11", "limit": 10},
        )
        == expected
    )
    [(request, timeout)] = opener.requests
    assert request.full_url == "https://discord.com/api/v10/channels/12/messages?after=11&limit=10"
    assert request.get_header("Authorization") == "Bot example.token"
    assert timeout == 10


def test_rate_limit_only_exposes_structured_facts(monkeypatch):
    response = HTTPError(
        "https://discord.com/api/v10/channels/12/messages",
        429,
        "private upstream detail",
        None,
        BytesIO(b'{"code": 20028, "retry_after": 2.5, "message": "private upstream detail"}'),
    )
    opener = Opener(response)
    monkeypatch.setattr(transport, "build_opener", lambda _: opener)

    with pytest.raises(transport.DiscordHTTPError) as result:
        transport.request_json(
            method="POST",
            path="/channels/12/messages",
            token="example.token",
            user_agent="DiscordBot Test",
            success_statuses=(200,),
            body={"content": "message"},
        )
    assert result.value.status == 429
    assert result.value.code == 20028
    assert result.value.retry_after == 2.5
    assert "private upstream detail" not in str(result.value)
    assert len(opener.requests) == 1


@pytest.mark.parametrize(
    ("status", "body"),
    [(201, b"{}"), (200, b"x" * (transport.MAX_RESPONSE + 1)), (200, b"123")],
)
def test_rejects_mismatched_status_and_invalid_responses(monkeypatch, status, body):
    monkeypatch.setattr(transport, "build_opener", lambda _: Opener(Response(status, body)))
    with pytest.raises(ValueError):
        transport.request_json(
            method="GET",
            path="/users/@me",
            token="example.token",
            user_agent="DiscordBot Test",
            success_statuses=(200,),
        )


def test_raw_transport_encodes_query_and_audit_reason(monkeypatch):
    from email.message import Message

    response = Response(201, b'{"id":"123"}')
    response.headers = Message()
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    opener = Opener(response)
    monkeypatch.setattr(transport, "build_opener", lambda handler: opener)
    assert transport.request_raw(
        method="POST",
        path="/channels/123/invites",
        authorization="Bearer example.token",
        user_agent="Test",
        success_statuses=(201,),
        data=b"name=example",
        content_type="application/x-www-form-urlencoded",
        query=[("limit", "10")],
        audit_reason="Test / change",
    ) == (201, "application/json", b'{"id":"123"}')
    [(request, _)] = opener.requests
    assert request.full_url.endswith("/channels/123/invites?limit=10")
    assert request.get_header("Authorization") == "Bearer example.token"
    assert request.get_header("Content-type") == "application/x-www-form-urlencoded"
    assert request.get_header("X-audit-log-reason") == "Test%20%2F%20change"
