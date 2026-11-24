"""The release archive passes the catalog's check for secret-looking fields.

The Flow Steward catalog refuses an archive in which any JSON or YAML file has a key
named like a credential holding non-empty text (build_index.py ``_SECRET_KEYS``:
``password``, ``secret``, ``api_key``, ``access_token``, ``private_key`` at the end
of the key). v0.1.2 failed its release on exactly that: the pinned Discord
documentation stored body parameters as keys, among them ``access_token``.

This test applies the same rule to every structured file the packager puts into the
archive, offline, so the problem shows up before a tag is pushed.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
#: Copied from the catalog's scripts/build_index.py (_SECRET_KEYS).
CATALOG_SECRET_KEYS = re.compile(
    r"(password|secret|api[_-]?key|access[_-]?token|private[_-]?key)$", re.I
)
STRUCTURED_SUFFIXES = {".json", ".yaml", ".yml"}
#: Directories the packager leaves out (.github/scripts/package_extension.py).
PACKAGER_EXCLUDED = {".git", ".github", "dist", "__pycache__"}


def _secret_values(node: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            if CATALOG_SECRET_KEYS.search(str(key)) and isinstance(value, str) and value.strip():
                found.append(here)
            found.extend(_secret_values(value, here))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            found.extend(_secret_values(item, f"{path}[{index}]"))
    return found


def _archived_structured_files() -> list[Path]:
    try:
        listed = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        listed = []
    if not listed:
        # No git here (a copy of the tree): every file on disk is what would be packed.
        listed = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file()]
    return [
        ROOT / name
        for name in listed
        if Path(name).suffix in STRUCTURED_SUFFIXES
        and not set(Path(name).parts) & PACKAGER_EXCLUDED
    ]


def test_no_archived_file_has_a_secret_looking_field() -> None:
    problems: list[str] = []
    for path in _archived_structured_files():
        text = path.read_text(encoding="utf-8")
        data = json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
        problems.extend(f"{path.relative_to(ROOT)}: {key}" for key in _secret_values(data))
    assert problems == []


def test_the_rule_catches_the_v0_1_2_shape() -> None:
    old = {"params": {"body": {"access_token": "an oauth2 access token"}}}
    new = {"params": {"body": [{"name": "access_token", "description": "an oauth2 access token"}]}}
    assert _secret_values(old) == ["params.body.access_token"]
    assert _secret_values(new) == []
