"""Populate Flow Steward's operation picker from the pinned route registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def operation_choices() -> dict[str, list[dict[str, str]]]:
    routes = json.loads((ROOT / "runtime/rest_routes.json").read_text())
    choices: dict[str, list[dict[str, str]]] = {
        "discord_rest_read": [],
        "discord_rest_write": [],
    }
    for operation, route in sorted(routes.items()):
        action = (
            "discord_rest_read"
            if route["method"] in {"GET", "HEAD", "OPTIONS"}
            else "discord_rest_write"
        )
        choices[action].append({"value": operation, "label": f"{route['method']} {route['path']}"})
    return choices


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = ROOT / "contracts/step_ui_manifest.yaml"
    manifest = yaml.safe_load(path.read_text())
    choices = operation_choices()
    for form in manifest["forms"]:
        if form["operation_id"] not in choices:
            continue
        for field in form["fields"]:
            if field["name"] == "operation_id":
                field["widget_type"] = "select"
                field["options"] = choices[form["operation_id"]]
            if field["name"] == "body":
                field["help_text"] = (
                    'Put the provider body in the data field, for example {"data":{"content":"Hello"}}.'
                )
    expected = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True)
    if args.check:
        if path.read_text() != expected:
            raise SystemExit("REST operation picker is out of date")
    else:
        path.write_text(expected)


if __name__ == "__main__":
    main()
