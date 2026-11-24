"""The UI pages, the step texts and the input labels that users read in Flow Steward."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_pages  # noqa: E402
import step_docs  # noqa: E402

#: SHA-256 of tests/reference/discord-endpoint-docs.json (extract_endpoint_docs.py run on
#: discord-api-docs 9b737ec).
ENDPOINT_DOCS_SHA256 = "0f8f0ec344fa6ca1634a0bd1a548f455262eaf6245d657542c236980acdd4020"
#: Inputs that must read the same in every step (with every path ID).
SAME_EVERYWHERE = {
    "channel_id",
    "guild_id",
    "user_id",
    "role_id",
    "message_id",
    "webhook_id",
    "application_id",
    "audit_reason",
    "body",
    "files",
    "file_artifacts",
    "all_pages",
    "media_type",
}


def load(name: str):
    return yaml.safe_load((ROOT / name).read_text())


def registered_pages() -> dict[str, dict]:
    refs = load("ui/ui_manifest.yaml")["pages"]
    return {ref["ref"]: load("ui/" + ref["ref"]) for ref in refs}


def test_the_generated_pages_are_current():
    for name, text in build_pages.pages().items():
        assert (ROOT / name).read_text() == text, name


def test_the_endpoint_docs_are_the_pinned_extraction():
    data = (ROOT / "tests/reference/discord-endpoint-docs.json").read_bytes()
    assert hashlib.sha256(data).hexdigest() == ENDPOINT_DOCS_SHA256
    docs = json.loads(data)
    assert docs["commit"] == "9b737ec51ee8d5076af0565d209a9adf8f590a27"
    assert docs["pages"] and all(re.fullmatch(r"[0-9a-f]{64}", v) for v in docs["pages"].values())


def test_every_registered_page_exists_once_and_has_no_markdown_table():
    pages = registered_pages()
    ids = [page["page_id"] for page in pages.values()]
    assert len(ids) == len(set(ids))
    for ref, page in pages.items():
        assert page["title"] and page["description"], ref
        for component in page["components"]:
            body = component.get("body", "")
            assert not any(line.lstrip().startswith("|") for line in body.splitlines()), ref


def test_the_pages_a_user_needs_are_there():
    ids = {page["page_id"] for page in registered_pages().values()}
    assert {
        "setup-guide",
        "connection",
        "connection-oauth2",
        "connection-webhook",
        "discord-api",
        "api-coverage",
        "changelog",
        "support",
    } <= ids
    assert {f"discord-api-{gid}" for gid, _, _ in step_docs.GROUPS} <= ids


def test_every_connection_type_has_a_form_on_its_page():
    types = {
        t["connection_type_id"] for t in load("contracts/connection_types.yaml")["connection_types"]
    }
    forms = {
        component["data"]["connection_type"]
        for page in registered_pages().values()
        for component in page["components"]
        if component["type"] == "connection_form"
    }
    assert forms == types


def test_every_step_is_on_exactly_one_group_page_with_what_it_does():
    manifest = load("contracts/operation_manifest.yaml")["operations"]
    generated = [op for op in manifest if op["operation_id"].startswith("rest_")]
    assert len(generated) == 258
    seen: dict[str, int] = defaultdict(int)
    for gid, _, _ in step_docs.GROUPS:
        body = load(f"ui/pages/discord-api-{gid}.yaml")["components"][0]["body"]
        for oid in re.findall(r"Action id `([a-z0-9_]+)`", body):
            seen[oid] += 1
    assert {op["operation_id"] for op in generated} == set(seen)
    assert set(seen.values()) == {1}
    for op in generated:
        assert not op["description"].startswith("Discord REST v10"), op["operation_id"]
        assert len(op["description"]) > len("Discord: GET /x."), op["operation_id"]


def test_every_step_has_a_description_and_a_unique_name():
    manifest = load("contracts/operation_manifest.yaml")["operations"]
    names = [op["display_name"] for op in manifest]
    assert len(names) == len(set(names))
    actions = load("ui/actions/actions.yaml")["actions"]
    assert all(action.get("description") for action in actions)


def test_every_input_has_a_label_and_help_and_the_same_input_reads_the_same():
    forms = load("contracts/step_ui_manifest.yaml")["forms"]
    texts: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for form in forms:
        for field in form["fields"]:
            assert field.get("label") and field.get("help_text"), (form["operation_id"], field)
            texts[field["name"], field["label"]].add(field["help_text"])
    for (name, label), variants in texts.items():
        if name in SAME_EVERYWHERE or name.endswith("_id") and name != "operation_id":
            # One name and label, one description; a query filter has its own label.
            assert len(variants) == 1, (name, label, variants)
    labels = {name: {label for (n, label) in texts if n == name} for name, _ in texts}
    for name in SAME_EVERYWHERE:
        plain = {label for label in labels.get(name, set()) if not label.endswith(" filter")}
        assert len(plain) <= 1, (name, plain)


def test_the_listing_says_what_the_extension_does_and_what_is_outside():
    manifest = load("extension.yaml")
    description = manifest["description"]
    assert len(description) >= 500
    for word in ("messages", "channels", "threads", "roles", "webhooks", "Gateway"):
        assert word in description
    for word in ("not part of", "not yet", "limitation", "outside this version", "pilot"):
        assert word not in description.lower()
