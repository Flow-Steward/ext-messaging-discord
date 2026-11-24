"""An answer cut off before its end is never taken for a whole one.

A real HTTP server on 127.0.0.1 sends the status, the headers and only part of the body,
then closes the connection: ``Content-Length`` promises more bytes than arrive, or a
chunked answer stops before its last chunk. ``http.client`` returns the short body of
the first case without an error, so the transport compares what arrived with what was
promised. A read is an error that changed nothing; a write Discord confirmed with its
documented status succeeds without data and with a warning (table T4).
"""

from __future__ import annotations

import socket
import threading
import urllib.request
from collections.abc import Iterator
from typing import Any

import main
import pytest
from test_finish import action

from runtime import transport


def _cut_by_length(body: bytes = b"{}", promised: int = 10) -> bytes:
    return (
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
        + f"Content-Length: {promised}\r\n\r\n".encode()
        + body
    )


def _cut_chunked() -> bytes:
    return (
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
        b'Transfer-Encoding: chunked\r\n\r\n5\r\n{"id"\r\n'
    )


class Server:
    """Answers every connection with ``answer`` and closes it."""

    def __init__(self, answer: bytes) -> None:
        self.answer = answer
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.requests = 0
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                conn.settimeout(5)
                data = b""
                while b"\r\n\r\n" not in data:
                    part = conn.recv(65536)
                    if not part:
                        break
                    data += part
                head, _, rest = data.partition(b"\r\n\r\n")
                for line in head.split(b"\r\n"):
                    if line.lower().startswith(b"content-length:"):
                        missing = int(line.split(b":")[1]) - len(rest)
                        while missing > 0:
                            part = conn.recv(65536)
                            if not part:
                                break
                            missing -= len(part)
                self.requests += 1
                conn.sendall(self.answer)

    def opener(self, request: Any, *, timeout_seconds: float, purpose: str) -> Any:
        """Sends the request to this server instead of Discord, over plain HTTP."""
        _, _, rest = request.full_url.partition("://")
        path = "/" + rest.partition("/")[2]
        local = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=request.data,
            method=request.get_method(),
            headers=dict(request.header_items()),
        )
        return urllib.request.urlopen(local, timeout=timeout_seconds)

    def close(self) -> None:
        self.sock.close()


@pytest.fixture
def serve(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    servers: list[Server] = []

    def start(answer: bytes) -> Server:
        server = Server(answer)
        servers.append(server)
        monkeypatch.setattr(transport, "open_pinned_url", server.opener, raising=False)
        return server

    yield start
    for server in servers:
        server.close()


@pytest.mark.parametrize("answer", [_cut_by_length(), _cut_chunked()], ids=["length", "chunked"])
def test_a_read_cut_off_is_an_error_without_effect(serve: Any, answer: bytes) -> None:
    server = serve(answer)
    result = main.dispatch(action("rest_get_channel"))
    assert server.requests == 1
    assert result["ok"] is False, result
    assert result["error_code"] == "invalid_response"
    assert result["definitely_no_external_effect"] is True


def test_a_whole_answer_with_its_length_is_read(serve: Any) -> None:
    body = b'{"id": "123"}'
    serve(_cut_by_length(body, len(body)))
    result = main.dispatch(action("rest_get_channel"))
    assert result["ok"] is True, result


@pytest.mark.parametrize("answer", [_cut_by_length(), _cut_chunked()], ids=["length", "chunked"])
def test_a_confirmed_write_cut_off_succeeds_without_data_and_warns(
    serve: Any, answer: bytes
) -> None:
    serve(answer)
    request = action("rest_update_channel")
    request["action"]["input"]["body"] = {"data": {"name": "general"}}
    result = main.dispatch(request)
    assert result["ok"] is True, result
    assert result["external_effect_status"] == "succeeded"
    assert result["result"]["response"]["data"] is None
    assert any("cut off" in warning for warning in result["result"]["warnings"])


def test_an_empty_body_where_json_is_documented_is_an_invalid_answer(serve: Any) -> None:
    serve(_cut_by_length(b"", 0))
    result = main.dispatch(action("rest_get_channel"))
    assert result["ok"] is False, result
    assert result["error_code"] == "invalid_response"
    assert result["definitely_no_external_effect"] is True
