"""Shared fakes: Discord answers without a network call."""

from __future__ import annotations

from email.message import Message
from io import BytesIO

from runtime import transport


def reply(status=200, body=b"{}", media="application/json", headers=None, unread=None):
    from runtime.transport import Reply

    return Reply(status, media, body, dict(headers or {}), unread)


def documented_reply(route, status, body=b"{}"):
    """A success answer with the media type Discord documents for the status."""
    types = route.get("response_media_types", {}).get(str(status)) or ["application/json"]
    if status == 204:
        return reply(status, b"", "")
    return reply(status, body if types[0] == "application/json" else b"x", types[0])


class Response(BytesIO):
    """What ``open_pinned_url`` returns: a status, headers and a readable body."""

    def __init__(self, status: int, body: bytes = b"", headers: dict | None = None):
        super().__init__(body)
        self.status = status
        self.headers = Message()
        for name, value in (headers or {}).items():
            self.headers[name] = value


class PinnedOpener:
    """Stands in for the SDK's ``open_pinned_url``; records every request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, *, timeout_seconds, purpose):
        self.requests.append((request, timeout_seconds, purpose))
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            return response(request)
        return response


def pinned(monkeypatch, *responses) -> PinnedOpener:
    opener = PinnedOpener(*responses)
    monkeypatch.setattr(transport, "open_pinned_url", opener, raising=False)
    return opener


class _LegacyOpener:
    def __init__(self, opener):
        self.opener = opener

    def open(self, request, timeout=None):
        return self.opener(request, timeout_seconds=timeout, purpose="")


def http(monkeypatch, *responses) -> PinnedOpener:
    """Answer every Discord request at the HTTP layer, whichever opener the transport
    uses, so a test exercises the whole runtime on the same answers."""
    opener = PinnedOpener(*responses)
    monkeypatch.setattr(transport, "open_pinned_url", opener, raising=False)
    monkeypatch.setattr(transport, "build_opener", lambda *_: _LegacyOpener(opener), raising=False)
    return opener


def json_response(status, value, headers=None):
    import json

    return Response(
        status, json.dumps(value).encode(), {"Content-Type": "application/json", **(headers or {})}
    )
