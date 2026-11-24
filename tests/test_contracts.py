"""Keep workflow actions, forms and effect declarations aligned."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return yaml.safe_load((ROOT / path).read_text())


def test_workflow_forms_and_effects_match_declared_actions():
    manifest = load("extension.yaml")
    refs = manifest["runtime"]["extension_contract_v2"]
    operations = load(refs["operation_manifest"])["operations"]
    actions = load(manifest["action_manifest"])["actions"]
    forms = load(refs["step_ui_manifest"])["forms"]
    effects = manifest["external_effects"]
    actions_by_id = {action["action_id"]: action for action in actions}
    forms_by_id = {form["operation_id"]: form for form in forms}
    effects_by_id = {effect["operation_id"]: effect for effect in effects}
    operation_ids = {operation["operation_id"] for operation in operations}
    assert operation_ids == actions_by_id.keys() == forms_by_id.keys()
    assert effects_by_id.keys() == {
        operation["operation_id"]
        for operation in operations
        if operation["operation_kind"] == "action"
    }

    for operation in operations:
        operation_id = operation["operation_id"]
        action = actions_by_id[operation_id]
        form = forms_by_id[operation_id]
        assert operation["workflow_visible"] is action["workflow_visible"] is True
        assert [field["name"] for field in operation["inputs"]] == [
            field["name"] for field in action["parameters"]
        ]
        assert {field["name"] for field in form["fields"]} == {
            field["name"]
            for field in operation["inputs"]
            if field["value_type"] != "connection_ref"
        }
        assert operation["error_codes"] == action["error_codes"]
        assert operation["result_fields"] == [
            f"result.{field}" for field in action["result_fields"]
        ]
        if operation_id in effects_by_id:
            effect = effects_by_id[operation_id]
            assert action["mutates_platform"] is True
            assert effect["effect_kind"] == operation["effect_kind"]
            assert effect["idempotency"] == "required"
            assert effect["test_mode_behavior"] == "suppress"


def test_rest_operation_pickers_cover_the_entire_catalog():
    from scripts.build_rest_choices import operation_choices

    manifest = load("contracts/step_ui_manifest.yaml")
    actual = {
        form["operation_id"]: field["options"]
        for form in manifest["forms"]
        for field in form["fields"]
        if form["operation_id"] in {"discord_rest_read", "discord_rest_write"}
        and field["name"] == "operation_id"
    }
    assert actual == operation_choices()
    assert sum(len(options) for options in actual.values()) == 250


def test_the_support_page_is_registered_as_the_catalog_requires():
    """The catalog lists a Flow Steward extension only with exactly one global page
    ``support`` titled Support, built of markdown components (build_index.py)."""
    pages = yaml.safe_load((ROOT / "ui/ui_manifest.yaml").read_text())["pages"]
    loaded = [yaml.safe_load((ROOT / "ui" / page["ref"]).read_text()) for page in pages]
    support = [page for page in loaded if page.get("page_id") == "support"]
    assert len(support) == 1
    assert support[0]["title"] == "Support"
    assert support[0]["project_scoped"] is False
    assert support[0]["components"]
    assert all(component["type"] == "markdown" for component in support[0]["components"])
    assert "github.com/Flow-Steward/ext-messaging-discord/issues" in str(support[0])


def test_the_user_agent_names_the_manifest_version():
    import main

    version = yaml.safe_load((ROOT / "extension.yaml").read_text())["version"]
    assert main.USER_AGENT.endswith(f", {version})")


def test_the_listing_names_its_catalog_categories():
    listing = yaml.safe_load((ROOT / "extension.yaml").read_text())["listing"]
    assert listing["category"] == "messaging"
    assert listing["categories"] == ["messaging"]
