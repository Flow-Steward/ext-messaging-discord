"""Verify the published REST inventory against the pinned Discord specification."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTTP_METHODS = {"get", "put", "post", "delete", "patch", "head", "options", "trace"}
SPEC_SHA256 = "ef338088f4c6a73fdb9840acd1ce2bf8f16c1870f4437bfc563418c7e0de7278"


def test_inventory_records_every_pinned_operation_and_its_contract():
    source = (ROOT / "tests/reference/discord-openapi.json").read_bytes()
    assert hashlib.sha256(source).hexdigest() == SPEC_SHA256
    spec = json.loads(source)
    report = json.loads((ROOT / "docs/discord-rest-inventory.json").read_text())
    registered = {(row["method"], row["path"]): row for row in report}
    assert len(registered) == len(report) == len({row["operation_id"] for row in report}) == 250

    for path, item in spec["paths"].items():
        for method in HTTP_METHODS.intersection(item):
            operation = item[method]
            row = registered.pop((method.upper(), path))
            assert row["operation_id"] == operation["operationId"]
            assert row["security"] == operation.get("security", spec.get("security", []))
            assert row["request_media_types"] == sorted(
                operation.get("requestBody", {}).get("content", {})
            )
            assert row["success_statuses"] == sorted(
                code for code in operation["responses"] if code.startswith("2")
            )
    assert not registered
