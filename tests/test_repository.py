"""The repository around the runtime: manifest, release workflows, README and the
read-only live check."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from test_individual_actions import ACTIONS
from test_rest_action import ROUTES

ROOT = Path(__file__).resolve().parents[1]


# -- 5. Manifest and repository --------------------------------------------------------


def test_the_manifest_names_the_repository_and_its_issues():
    manifest = yaml.safe_load((ROOT / "extension.yaml").read_text())
    assert manifest["vendor"] == {
        "name": "Flow Steward",
        "website_url": "https://github.com/Flow-Steward/ext-messaging-discord",
        "support_url": "https://github.com/Flow-Steward/ext-messaging-discord/issues",
    }
    assert manifest["listing"]["category"] == "messaging"


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/ci.yml",
        ".github/workflows/release.yml",
        ".github/workflows/codeql.yml",
        ".github/scripts/catalog_check.py",
        ".github/scripts/package_extension.py",
        ".github/scripts/release_notes.py",
        ".github/dependabot.yml",
    ],
)
def test_the_repository_carries_the_release_workflows(path):
    assert (ROOT / path).is_file()


# -- 11. README ------------------------------------------------------------------------


def test_the_readme_follows_the_extension_structure():
    text = (ROOT / "README.md").read_text()
    assert text.startswith("# Discord integration for Flow Steward\n")
    headings = [line[3:] for line in text.splitlines() if line.startswith("## ")]
    assert headings == [
        "What is this",
        "What you can automate",
        "Why teams use it",
        "What's inside",
        "Get started",
        "Requirements",
        "FAQ",
        "In your language",
        "Links",
        "For developers",
    ]
    lowered = text.lower()
    for word in ("todo", "not yet", "coming soon", "work in progress"):
        assert word not in lowered


# -- 12. Live test -------------------------------------------------------------------


def test_the_live_check_needs_a_token_file_and_only_reads(monkeypatch):
    import test_live

    monkeypatch.delenv("DISCORD_TOKEN_FILE", raising=False)
    assert test_live.token() is None
    assert test_live.LIVE_ACTIONS
    for action_id in test_live.LIVE_ACTIONS:
        operation = ACTIONS[action_id]["operation_id"] if action_id in ACTIONS else "get_my_user"
        assert ROUTES[operation]["method"] == "GET"
