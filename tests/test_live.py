"""Read-only checks against the real Discord API.

They run only when ``DISCORD_TOKEN_FILE`` names a file holding a bot token, and send
GET requests only: the bot's identity and the servers it is in (all pages).

    DISCORD_TOKEN_FILE=~/discord-bot-token python -m pytest tests/test_live.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import main

#: The steps the live check runs; each is a GET.
LIVE_ACTIONS = ("test_connection", "rest_get_my_user", "rest_list_my_guilds")


def token() -> str | None:
    path = os.environ.get("DISCORD_TOKEN_FILE", "").strip()
    if not path:
        return None
    value = Path(path).expanduser().read_text(encoding="utf-8").strip()
    return value or None


def run(action_id: str, **inputs: object) -> dict:
    secret = token()
    assert secret is not None
    return main.dispatch(
        {
            "contract_version": "extension_host_v2",
            "mode": "action",
            "runtime_context": {
                "step_id": "live",
                "step_execution_id": "live-read",
                "test_mode": False,
            },
            "action": {
                "action_id": action_id,
                "input": {"connection_ref": "live", **inputs},
                "target": {
                    "connection": {
                        "connection_id": "live",
                        "connection_type": "discord_bot",
                        "secrets": {"bot_token": secret},
                    }
                },
            },
        }
    )


live = pytest.mark.skipif(token() is None, reason="DISCORD_TOKEN_FILE is not set")


@live
def test_the_bot_identity_is_read():
    result = run("test_connection")
    assert result["ok"] is True, result
    assert result["result"]["bot_id"].isdigit()
    assert result["result"]["rate_limit"]["limit"] is not None
    secret = token()
    assert secret is not None and secret not in repr(result)


@live
def test_the_dedicated_identity_step_matches():
    identity = run("test_connection")["result"]["bot_id"]
    result = run("rest_get_my_user")
    assert result["ok"] is True, result
    assert result["result"]["response"]["data"]["id"] == identity


@live
def test_every_server_of_the_bot_is_read():
    result = run("rest_list_my_guilds", all_pages=True)
    assert result["ok"] is True, result
    assert result["result"]["complete"] is True
    assert isinstance(result["result"]["response"]["data"], list)
