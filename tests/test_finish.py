"""Reads that fail loudly, table T for writes, the output budget, whole lists, files,
redaction, test runs, the pinned transport and Discord's rate limit facts."""

from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest
import yaml

import main
from discord_fakes import Response, http, json_response
from runtime import rest
from test_flowsteward_discord import invocation
from test_individual_actions import ACTIONS, independent_invocation
from test_rest_action import ROUTES

ROOT = Path(__file__).resolve().parents[1]
MIB = 1024 * 1024


def action(action_id, **inputs):
    request, _, _ = independent_invocation(action_id)
    request["action"]["input"].update(inputs)
    return request


def no_effect(result, code):
    assert result["ok"] is False, result
    assert result["error_code"] == code
    assert result["definitely_no_external_effect"] is True
    assert result["external_effect_status"] == "failed"


# -- 1. A read never returns what it could not read --------------------------------


class CutOff(Response):
    def read(self, size=-1):
        raise ConnectionResetError


def deep(levels):
    return ("[" * levels + "]" * levels).encode()


READ_FAILURES = {
    "larger_than_8_mib": (
        lambda: Response(
            200, b"[" + b"0," * (4 * MIB) + b"0]", {"Content-Type": "application/json"}
        ),
        "response_too_large",
    ),
    "cut_off": (lambda: CutOff(200, b"", {"Content-Type": "application/json"}), "invalid_response"),
    "undocumented_status": (
        lambda: Response(201, b"{}", {"Content-Type": "application/json"}),
        "invalid_response",
    ),
    "not_json": (
        lambda: Response(200, b"{bad", {"Content-Type": "application/json"}),
        "invalid_response",
    ),
    "html": (
        lambda: Response(200, b"<html>", {"Content-Type": "text/html"}),
        "invalid_response",
    ),
    "empty_where_json_is_documented": (
        lambda: Response(200, b"", {"Content-Type": "application/json"}),
        "invalid_response",
    ),
    "nested_too_deeply": (
        lambda: Response(200, deep(46), {"Content-Type": "application/json"}),
        "invalid_response",
    ),
}


@pytest.mark.parametrize("case", sorted(READ_FAILURES))
def test_a_read_that_cannot_be_read_is_an_error_without_effect(monkeypatch, case):
    make, code = READ_FAILURES[case]
    http(monkeypatch, make())
    no_effect(main.dispatch(action("rest_get_channel")), code)


@pytest.mark.parametrize("case", ["cut_off", "html", "empty_where_json_is_documented"])
def test_the_generic_read_and_the_dedicated_read_fail_alike(monkeypatch, case):
    make, code = READ_FAILURES[case]
    http(monkeypatch, make())
    request = invocation("discord_rest_read")
    request["action"]["input"].update(
        operation_id="get_channel", path_parameters={"channel_id": "123"}
    )
    no_effect(main.dispatch(request), code)
    http(monkeypatch, make())
    get = invocation("get_channel")
    get["action"]["input"]["channel_id"] = "123"
    no_effect(main.dispatch(get), code)


# -- 1. Table T: the outcome of a write ---------------------------------------------

BODIES = {
    "empty": lambda: b"",
    "good": lambda: b'{"id":"77"}',
    "not_json_start": lambda: b"accepted",
    "unparsable": lambda: b'{"id":',
    "too_deep": lambda: deep(46),
    "larger_than_8_mib": lambda: b"[" + b"0," * (4 * MIB) + b"0]",
    "cut_off": None,
}
TYPES = {"json": "application/json", "html": "text/html", "none": None}
#: update_channel documents JSON for 200; modify_current_user_nick documents 200 without
#: a body (discord-api-docs guild.mdx).
WRITES = {
    "json_promised": "rest_update_channel",
    "no_body_documented": "rest_modify_current_user_nick",
}


def expected_outcome(write, kind, body):
    """Table T, written independently of the runtime."""
    promised = write == "json_promised"
    if promised and kind == "html":
        return "unknown"  # T2
    if body in {"cut_off", "larger_than_8_mib"}:
        return "no_data"  # T4
    if body == "empty":
        return "success_empty"
    if promised:
        if body in {"not_json_start", "unparsable"}:
            return "unknown"  # T3
        if body == "too_deep":
            return "no_data"  # T4
        return "success_data"
    if kind == "json" and body == "good":
        return "success_data"
    if kind == "json" and body == "too_deep":
        return "no_data"
    return "text"


@pytest.mark.parametrize("write", sorted(WRITES))
@pytest.mark.parametrize("kind", sorted(TYPES))
@pytest.mark.parametrize("body", sorted(BODIES))
def test_table_t_decides_every_write_outcome(monkeypatch, write, kind, body):
    headers = {"Content-Type": TYPES[kind]} if TYPES[kind] else {}
    if body == "cut_off":
        response = CutOff(200, b"", headers)
    else:
        response = Response(200, BODIES[body](), headers)
    opener = http(monkeypatch, response)
    request = action(WRITES[write])
    if write == "json_promised":
        request["action"]["input"]["body"] = {"data": {"name": "general"}}
    result = main.dispatch(request)
    assert len(opener.requests) == 1
    outcome = expected_outcome(write, kind, body)
    if outcome == "unknown":
        assert result["ok"] is False
        assert result["error_code"] == "timeout_unknown"
        assert result["external_effect_status"] == "timeout_unknown"
        assert result["definitely_no_external_effect"] is False
        return
    assert result["ok"] is True, result
    assert result["external_effect_status"] == "succeeded"
    output = result["result"]
    assert output["processing"] == "completed"
    data = output["response"]["data"]
    if outcome == "success_data":
        assert data == {"id": "77"} and output["warnings"] == []
    elif outcome == "success_empty":
        assert data is None and output["warnings"] == []
    elif outcome == "no_data":
        assert data is None and len(output["warnings"]) == 1
    else:
        assert isinstance(data, str) and "not JSON" in output["warnings"][0]


def test_an_undocumented_success_status_of_a_write_is_unknown(monkeypatch):
    http(monkeypatch, Response(202, b"{}", {"Content-Type": "application/json"}))
    result = main.dispatch(action("rest_update_channel", body={"data": {"name": "x"}}))
    assert result["error_code"] == "timeout_unknown"
    assert result["definitely_no_external_effect"] is False


# -- 2. 8 MiB answers and the host's output budget ------------------------------------


def test_a_large_member_page_is_read_whole(monkeypatch):
    members = [{"user": {"id": str(n), "username": "u" * 300}} for n in range(1, 1001)]
    raw = json.dumps(members).encode()
    assert 256_000 < len(raw) < 3_000_000
    http(monkeypatch, Response(200, raw, {"Content-Type": "application/json"}))
    result = main.dispatch(action("rest_list_guild_members", limit=1000))
    assert result["ok"] is True
    assert len(result["result"]["response"]["data"]) == 1000


def test_a_read_larger_than_the_step_output_is_refused_whole(monkeypatch):
    raw = json.dumps([{"id": str(n), "content": "x" * 3000} for n in range(1, 1300)]).encode()
    assert 3_500_000 < len(raw) < 8 * MIB
    http(monkeypatch, Response(200, raw, {"Content-Type": "application/json"}))
    no_effect(main.dispatch(action("rest_list_messages")), "response_too_large")


def test_the_whole_envelope_is_measured(monkeypatch):
    from runtime import budget

    # The data alone fits; with the envelope around it, it does not.
    text = "x" * (budget.MAX_SERIALIZED_BYTES - 40)
    assert budget.written_size({"data": text}) <= budget.MAX_SERIALIZED_BYTES
    raw = json.dumps({"id": "1", "topic": text}).encode()
    http(monkeypatch, Response(200, raw, {"Content-Type": "application/json"}))
    no_effect(main.dispatch(action("rest_get_channel")), "response_too_large")


def test_a_confirmed_write_too_large_for_the_output_keeps_its_success(monkeypatch):
    raw = json.dumps({"id": "1", "topic": "x" * 3_600_000}).encode()
    http(monkeypatch, Response(200, raw, {"Content-Type": "application/json"}))
    result = main.dispatch(action("rest_update_channel", body={"data": {"name": "x"}}))
    assert result["external_effect_status"] == "succeeded"
    assert result["result"]["response"]["data"] is None
    assert "too large" in result["result"]["warnings"][0]
    assert len(json.dumps(result)) < 3_500_000


def test_the_budget_counts_nodes_depth_and_bytes():
    from runtime import budget

    assert (budget.MAX_SERIALIZED_BYTES, budget.MAX_NODES, budget.MAX_DEPTH) == (
        3_500_000,
        2_000_000,
        48,
    )
    assert budget.fits({"a": [1, 2, 3]})
    nested: object = 0
    for _ in range(49):
        nested = [nested]
    assert budget.fits(nested)  # the innermost list is 48 levels below the outermost
    assert not budget.fits([nested])
    assert budget.measure([0] * 10)[0] == 11
    assert not budget.fits({"x": "y" * 3_500_000})


# -- 3. Whole lists ------------------------------------------------------------------


def spec_cursor_lists():
    from scripts.build_rest_registry import load_spec

    spec = load_spec()
    found = set()
    for item in spec["paths"].values():
        for method, operation in item.items():
            if method != "get" or not isinstance(operation, dict):
                continue
            names = {
                p["name"]
                for p in [*item.get("parameters", []), *operation.get("parameters", [])]
                if p.get("in") == "query"
            }
            if "limit" in names and names & {"before", "after"}:
                found.add(operation["operationId"])
    return found


def test_every_cursor_list_of_the_catalog_has_the_all_pages_mode():
    from runtime.paging import PAGING

    assert set(PAGING) == spec_cursor_lists()
    for operation in PAGING:
        names = {field["name"] for field in ACTIONS[f"rest_{operation}"]["fields"]}
        assert "all_pages" in names
        assert set(PAGING[operation].directions) <= set(ROUTES[operation]["query_parameters"])


def members(first, last):
    return [{"user": {"id": str(n)}} for n in range(first, last + 1)]


def queries(opener):
    from urllib.parse import parse_qsl, urlsplit

    return [dict(parse_qsl(urlsplit(request.full_url).query)) for request, _, _ in opener.requests]


def test_all_pages_continues_exactly_until_an_empty_page(monkeypatch):
    opener = http(
        monkeypatch,
        json_response(200, members(1, 1000)),
        json_response(200, members(1001, 1500)),
        json_response(200, []),
    )
    result = main.dispatch(action("rest_list_guild_members", all_pages=True))
    assert result["ok"] is True, result
    output = result["result"]
    assert [q.get("after") for q in queries(opener)] == ["0", "1000", "1500"]
    assert {q["limit"] for q in queries(opener)} == {"1000"}
    assert [m["user"]["id"] for m in output["response"]["data"]] == [str(n) for n in range(1, 1501)]
    assert (output["complete"], output["next_cursor"], output["pages"]) == (True, None, 3)


def test_a_short_page_does_not_end_the_list(monkeypatch):
    opener = http(
        monkeypatch,
        json_response(200, members(1, 3)),
        json_response(200, members(4, 4)),
        json_response(200, []),
    )
    result = main.dispatch(action("rest_list_guild_members", all_pages=True, limit=10))
    assert len(opener.requests) == 3
    assert len(result["result"]["response"]["data"]) == 4


def test_messages_go_back_from_the_smallest_id(monkeypatch):
    page1 = [{"id": "30"}, {"id": "20"}]
    page2 = [{"id": "10"}]
    opener = http(
        monkeypatch, json_response(200, page1), json_response(200, page2), json_response(200, [])
    )
    result = main.dispatch(action("rest_list_messages", all_pages=True, limit=2))
    assert [q.get("before") for q in queries(opener)] == [None, "20", "10"]
    assert [m["id"] for m in result["result"]["response"]["data"]] == ["30", "20", "10"]
    assert result["result"]["complete"] is True


def test_a_given_cursor_sets_the_direction(monkeypatch):
    opener = http(
        monkeypatch, json_response(200, [{"id": "11"}, {"id": "12"}]), json_response(200, [])
    )
    result = main.dispatch(action("rest_list_messages", all_pages=True, after="10"))
    assert [q.get("after") for q in queries(opener)] == ["10", "12"]
    assert result["result"]["complete"] is True


def thread(identifier, stamp):
    return {"id": identifier, "thread_metadata": {"archive_timestamp": stamp}}


def test_has_more_false_ends_an_archived_thread_list(monkeypatch):
    opener = http(
        monkeypatch,
        json_response(
            200,
            {
                "threads": [
                    thread("2", "2024-05-02T00:00:00+00:00"),
                    thread("1", "2024-05-01T00:00:00+00:00"),
                ],
                "members": [{"id": "2", "user_id": "9"}],
                "has_more": True,
            },
        ),
        json_response(
            200,
            {
                "threads": [thread("0", "2024-04-01T00:00:00+00:00")],
                "members": [{"id": "2", "user_id": "9"}],
                "has_more": False,
            },
        ),
    )
    result = main.dispatch(action("rest_list_public_archived_threads", all_pages=True))
    assert [q.get("before") for q in queries(opener)] == [None, "2024-05-01T00:00:00+00:00"]
    data = result["result"]["response"]["data"]
    assert [t["id"] for t in data["threads"]] == ["2", "1", "0"]
    assert data["members"] == [{"id": "2", "user_id": "9"}]
    assert data["has_more"] is False
    assert result["result"]["complete"] is True


def test_an_empty_page_that_says_more_follow_is_an_unfinished_read(monkeypatch):
    http(monkeypatch, json_response(200, {"threads": [], "members": [], "has_more": True}))
    no_effect(
        main.dispatch(action("rest_list_public_archived_threads", all_pages=True)),
        "invalid_response",
    )


def test_a_cursor_that_does_not_move_is_an_unfinished_read(monkeypatch):
    http(monkeypatch, json_response(200, [{"user": {"id": "0"}}]))
    no_effect(main.dispatch(action("rest_list_guild_members", all_pages=True)), "invalid_response")


def test_the_list_stops_before_a_page_that_does_not_fit(monkeypatch):
    big = [{"user": {"id": str(n), "bio": "b" * 2000}} for n in range(1, 1001)]
    more = [{"user": {"id": str(n), "bio": "b" * 2000}} for n in range(1001, 2001)]
    opener = http(monkeypatch, json_response(200, big), json_response(200, more))
    result = main.dispatch(action("rest_list_guild_members", all_pages=True))
    assert len(opener.requests) == 2
    output = result["result"]
    assert len(output["response"]["data"]) == 1000
    assert (output["complete"], output["next_cursor"], output["pages"]) == (False, "1000", 1)
    assert "after=1000" in output["warnings"][0]
    assert len(json.dumps(result)) <= 3_500_000


def test_the_list_stops_when_the_time_is_used_up(monkeypatch):
    from runtime import rest_action

    ticks = iter([0.0, 0.0, 25.0, 25.0])
    monkeypatch.setattr(rest_action.time, "monotonic", lambda: next(ticks))
    opener = http(monkeypatch, json_response(200, members(1, 2)), json_response(200, members(3, 4)))
    result = main.dispatch(action("rest_list_guild_members", all_pages=True))
    assert len(opener.requests) == 1
    assert (result["result"]["complete"], result["result"]["next_cursor"]) == (False, "2")


def test_a_rate_limited_later_page_returns_what_was_read(monkeypatch):
    limited = HTTPError(
        "https://discord.com", 429, "x", None, BytesIO(b'{"retry_after": 1.5, "global": false}')
    )
    http(monkeypatch, json_response(200, members(1, 2)), limited)
    result = main.dispatch(action("rest_list_guild_members", all_pages=True))
    assert result["ok"] is True
    assert (result["result"]["complete"], result["result"]["next_cursor"]) == (False, "2")
    assert "rate limited" in result["result"]["warnings"][0]


def test_a_rate_limited_first_page_is_rate_limited(monkeypatch):
    limited = HTTPError("https://discord.com", 429, "x", None, BytesIO(b'{"retry_after": 3}'))
    http(monkeypatch, limited)
    result = main.dispatch(action("rest_list_guild_members", all_pages=True))
    assert result["error_code"] == "rate_limited"
    assert result["retry_after_seconds"] == 3


def test_around_has_no_whole_list(monkeypatch):
    opener = http(monkeypatch, json_response(200, []))
    result = main.dispatch(action("rest_list_messages", all_pages=True, around="5"))
    assert result["error_code"] == "invalid_payload"
    assert opener.requests == []


def test_one_page_says_where_the_next_begins(monkeypatch):
    http(monkeypatch, json_response(200, members(1, 2)))
    output = main.dispatch(action("rest_list_guild_members", limit=2))["result"]
    assert (output["next_cursor"], output["complete"], output["pages"]) == ("2", False, 1)
    http(monkeypatch, json_response(200, []))
    output = main.dispatch(action("rest_list_guild_members", limit=2))["result"]
    assert (output["next_cursor"], output["complete"]) == (None, True)


def test_the_dedicated_message_list_reads_all_pages(monkeypatch):
    opener = http(monkeypatch, json_response(200, [{"id": "5"}]), json_response(200, []))
    request = invocation("list_messages")
    request["action"]["input"].update(channel_id="123", all_pages=True)
    result = main.dispatch(request)
    assert result["result"]["items"] == [{"id": "5"}]
    assert result["result"]["complete"] is True
    assert queries(opener)[1] == {"before": "5", "limit": "100"}


# -- 6. Files --------------------------------------------------------------------------


def parts(call):
    from email import policy
    from email.parser import BytesParser

    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {call['content_type']}\r\nMIME-Version: 1.0\r\n\r\n".encode() + call["data"]
    )
    return [part for part in message.iter_parts() if part.get_filename()]


def capture(monkeypatch):
    calls = []

    def send(**kwargs):
        from discord_fakes import reply

        calls.append(kwargs)
        return reply(200, b'{"id":"1"}')

    monkeypatch.setattr(rest, "request_raw", send)
    return calls


def artifact_grant(tmp_path, handle, content):
    path = tmp_path / handle
    path.write_bytes(content)
    return {
        "inputs": [
            {
                "artifact_id": handle,
                "binding_key": "discord_file",
                "access": {
                    "transport": "presigned_url",
                    "mode": "read",
                    "download_url": path.as_uri(),
                },
            }
        ]
    }


def test_a_workflow_file_is_sent_as_a_file_with_its_type(monkeypatch, tmp_path):
    calls = capture(monkeypatch)
    request = action(
        "rest_create_message",
        media_type="multipart/form-data",
        body={"data": {"content": "report"}},
        file_artifacts=[{"field": "files[0]", "filename": "chart.PNG", "artifact_handle": "art-1"}],
    )
    request["action"]["artifacts"] = artifact_grant(tmp_path, "art-1", b"\x89PNG-bytes")
    result = main.dispatch(request)
    assert result["ok"] is True, result
    [part] = parts(calls[0])
    assert part.get_filename() == "chart.PNG"
    assert part.get_content_type() == "image/png"
    assert part.get_payload(decode=True) == b"\x89PNG-bytes"


TWENTY_MIB = 20 * 1024 * 1024


def test_a_twenty_mib_workflow_file_is_sent_whole(monkeypatch, tmp_path):
    calls = capture(monkeypatch)
    content = b"\x89PNG" + b"0" * (TWENTY_MIB - 4)
    request = action(
        "rest_create_message",
        media_type="multipart/form-data",
        body={"data": {"content": "video"}},
        file_artifacts=[{"field": "files[0]", "filename": "big.png", "artifact_handle": "art-20"}],
    )
    request["action"]["artifacts"] = artifact_grant(tmp_path, "art-20", content)
    result = main.dispatch(request)
    assert result["ok"] is True, result
    [part] = parts(calls[0])
    assert len(part.get_payload(decode=True)) == TWENTY_MIB


def test_a_workflow_file_one_byte_over_twenty_mib_sends_nothing(monkeypatch, tmp_path):
    calls = capture(monkeypatch)
    request = action(
        "rest_create_message",
        media_type="multipart/form-data",
        body={"data": {"content": "video"}},
        file_artifacts=[{"field": "files[0]", "filename": "big.png", "artifact_handle": "art-21"}],
    )
    request["action"]["artifacts"] = artifact_grant(tmp_path, "art-21", b"0" * (TWENTY_MIB + 1))
    result = main.dispatch(request)
    assert result["ok"] is False and result["error_code"] == "invalid_payload", result
    assert calls == []


def test_the_twenty_mib_limit_is_checked_per_file():
    from runtime import files

    def read(_handle):
        return b"0" * (TWENTY_MIB + 1)

    with pytest.raises(ValueError, match="larger than 20 MiB"):
        files.file_parts(
            "rest_create_message",
            [],
            [{"field": "files[0]", "filename": "a.bin", "artifact_handle": "h"}],
            read_artifact=read,
            valid_name=lambda _name: True,
        )


def test_workflow_file_grants_follow_discords_twenty_mib_limit():
    policies = yaml.safe_load((ROOT / "contracts/artifact_policies.yaml").read_text())["policies"]
    sizes = {item["max_size_bytes"] for policy in policies for item in policy["inputs"]}
    assert sizes == {TWENTY_MIB}


def test_a_workflow_file_that_cannot_be_read_sends_nothing(monkeypatch):
    calls = capture(monkeypatch)
    request = action(
        "rest_create_message",
        media_type="multipart/form-data",
        file_artifacts=[{"field": "files[0]", "filename": "a.txt", "artifact_handle": "missing"}],
    )
    assert main.dispatch(request)["error_code"] == "invalid_payload"
    assert calls == []


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("a.png", "image/png"),
        ("a.jpg", "image/jpeg"),
        ("a.jpeg", "image/jpeg"),
        ("a.gif", "image/gif"),
        ("a.webp", "image/webp"),
        ("a.mp4", "video/mp4"),
        ("a.mp3", "audio/mpeg"),
        ("a.json", "application/json"),
        ("a.pdf", "application/octet-stream"),
        ("noextension", "application/octet-stream"),
    ],
)
def test_a_base64_file_part_takes_the_type_of_its_extension(monkeypatch, filename, content_type):
    calls = capture(monkeypatch)
    request = action(
        "rest_create_message",
        media_type="multipart/form-data",
        files=[{"field": "files[0]", "filename": filename, "data_base64": "AAE="}],
    )
    assert main.dispatch(request)["ok"] is True
    [part] = parts(calls[0])
    assert part.get_content_type() == content_type


@pytest.mark.parametrize(
    ("filename", "size", "ok"),
    [
        ("s.png", 10, True),
        ("s.apng", 10, True),
        ("s.gif", 10, True),
        ("s.json", 10, True),
        ("s.jpg", 10, False),
        ("s.png", 512 * 1024, True),
        ("s.png", 512 * 1024 + 1, False),
    ],
)
def test_a_sticker_is_a_png_apng_gif_or_lottie_file_of_512_kib(monkeypatch, filename, size, ok):
    calls = capture(monkeypatch)
    request = action(
        "rest_create_guild_sticker",
        body={"data": {"name": "Fixture", "tags": "x"}},
        files=[
            {
                "field": "file",
                "filename": filename,
                "data_base64": base64.b64encode(b"\0" * size).decode(),
            }
        ],
    )
    result = main.dispatch(request)
    assert result["ok"] is ok
    assert len(calls) == (1 if ok else 0)


def test_multipart_actions_declare_the_workflow_file_input_and_its_grant():
    policies = yaml.safe_load((ROOT / "contracts/artifact_policies.yaml").read_text())["policies"]
    granted = {policy["operation_id"] for policy in policies}
    multipart = {
        action_id
        for action_id, record in ACTIONS.items()
        if "multipart/form-data" in ROUTES[record["operation_id"]]["request_media_types"]
    }
    assert granted == multipart | {"discord_rest_write"}
    for action_id in multipart:
        assert "file_artifacts" in {field["name"] for field in ACTIONS[action_id]["fields"]}
    manifest = yaml.safe_load((ROOT / "extension.yaml").read_text())
    assert (
        manifest["runtime"]["extension_contract_v2"]["artifact_policies"]
        == "contracts/artifact_policies.yaml"
    )


# -- 7. Redaction of values found in the answer ----------------------------------------


def test_a_short_value_under_a_credential_name_does_not_corrupt_other_text():
    value = {"token": "1", "name": "room 101"}
    assert rest.redact_response(value, ()) == {"name": "room 101"}


def test_a_long_value_under_a_credential_name_is_removed_everywhere():
    value = {"token": "abcdefgh", "name": "see abcdefgh"}
    assert rest.redact_response(value, ()) == {"name": "see [redacted]"}


def test_the_connection_secret_is_always_removed():
    assert rest.redact_response({"name": "x abc y"}, ("abc",)) == {"name": "x [redacted] y"}


# -- 8. Test runs ----------------------------------------------------------------------


def test_a_test_run_write_reports_no_effect(monkeypatch):
    opener = http(monkeypatch, json_response(200, {}))
    request = action("rest_update_channel", body={"data": {"name": "x"}})
    request["runtime_context"]["test_mode"] = True
    result = main.dispatch(request)
    assert result["ok"] is True
    assert result["external_effect_status"] == "failed"
    assert result["definitely_no_external_effect"] is True
    assert result["result"]["processing"] is None
    assert opener.requests == []


def test_a_test_run_of_the_message_step_reports_no_effect(monkeypatch):
    opener = http(monkeypatch, json_response(200, {}))
    result = main.dispatch(invocation(test_mode=True))
    assert result["external_effect_status"] == "failed"
    assert result["definitely_no_external_effect"] is True
    assert result["result"]["processing"] is None
    assert result["result"]["message_id"] is None
    assert opener.requests == []


def test_a_disabled_operation_is_disabled_in_a_test_run_too(monkeypatch):
    opener = http(monkeypatch, json_response(200, {}))
    request, _, _ = independent_invocation("rest_batch_edit_application_command_permissions")
    request["runtime_context"]["test_mode"] = True
    result = main.dispatch(request)
    assert result["error_code"] == "operation_disabled"
    assert opener.requests == []


# -- 9. Pinned transport ---------------------------------------------------------------


def test_a_host_that_fails_the_pinning_check_is_no_effect(monkeypatch):
    from flowsteward_extension_sdk import PinnedPeerError

    http(monkeypatch, PinnedPeerError("Discord API host resolves to disallowed address"))
    result = main.dispatch(action("rest_update_channel", body={"data": {"name": "x"}}))
    no_effect(result, "provider_unavailable")


def test_a_lost_answer_of_a_write_stays_unknown(monkeypatch):
    http(monkeypatch, URLError("reset"))
    result = main.dispatch(action("rest_update_channel", body={"data": {"name": "x"}}))
    assert result["error_code"] == "timeout_unknown"
    assert result["definitely_no_external_effect"] is False


# -- 10. Rate limits -------------------------------------------------------------------

LIMIT_HEADERS = {
    "X-RateLimit-Limit": "5",
    "X-RateLimit-Remaining": "0",
    "X-RateLimit-Reset-After": "0.25",
    "X-RateLimit-Bucket": "b1",
}


def test_every_step_returns_discord_rate_limit_facts(monkeypatch):
    http(monkeypatch, json_response(200, {"id": "1"}, LIMIT_HEADERS))
    result = main.dispatch(action("rest_get_channel"))
    assert result["result"]["rate_limit"] == {
        "limit": 5,
        "remaining": 0,
        "reset_after": 0.25,
        "bucket": "b1",
        "global": False,
    }
    http(monkeypatch, json_response(200, {"id": "1"}, LIMIT_HEADERS))
    request = invocation()
    assert main.dispatch(request)["result"]["rate_limit"]["bucket"] == "b1"


def test_a_429_reports_retry_after_and_global_and_is_not_retried(monkeypatch):
    from email.message import Message

    headers = Message()
    headers["X-RateLimit-Global"] = "true"
    limited = HTTPError(
        "https://discord.com", 429, "x", headers, BytesIO(b'{"retry_after": 2.5, "global": true}')
    )
    opener = http(monkeypatch, limited)
    result = main.dispatch(action("rest_update_channel", body={"data": {"name": "x"}}))
    assert len(opener.requests) == 1
    assert result["error_code"] == "rate_limited"
    assert result["retry_after_seconds"] == 2.5
    assert result["rate_limit_global"] is True
    assert result["result"]["rate_limit"]["global"] is True
    assert result["definitely_no_external_effect"] is True


def test_every_operation_declares_the_rate_limit_and_warnings_outputs():
    operations = yaml.safe_load((ROOT / "contracts/operation_manifest.yaml").read_text())
    for operation in operations["operations"]:
        names = {output["name"] for output in operation["outputs"]}
        assert {"rate_limit", "warnings"} <= names, operation["operation_id"]
        if operation["operation_kind"] == "action":
            assert "processing" in names
        else:
            assert {"invalid_response"} <= set(operation["error_codes"])
