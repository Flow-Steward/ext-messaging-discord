"""Verify route construction for all operations in the Discord v10 inventory."""

import json
from pathlib import Path

import pytest
from runtime.routes import request_target
from scripts.build_rest_registry import build_routes, load_spec

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / "runtime/rest_routes.json").read_text())


def test_generated_registry_matches_pinned_spec():
    assert REGISTRY == build_routes(load_spec())
    assert len(REGISTRY) == 258


@pytest.mark.parametrize("operation_id", sorted(REGISTRY))
def test_every_operation_binds_its_exact_method_and_path(operation_id):
    row = REGISTRY[operation_id]
    secret_names = set(row["secret_path_parameters"])
    values = {name: "1234" for name in row["path_parameters"] if name not in secret_names}
    credentials = {name: "sample.route.credential" for name in secret_names}
    target = request_target(operation_id, path_parameters=values, connection_secrets=credentials)
    assert target.method == row["method"]
    assert target.success_statuses == tuple(row["success_statuses"])
    assert target.path == row["path"].format(**values, **credentials)
    assert "sample.route.credential" not in repr(target)


def test_route_credentials_are_not_workflow_inputs():
    with pytest.raises(ValueError, match="Path parameters"):
        request_target(
            "get_webhook_by_token",
            path_parameters={"webhook_id": "1234", "webhook_token": "untrusted"},
        )


def test_emoji_is_encoded_as_one_path_segment():
    target = request_target(
        "add_my_message_reaction",
        path_parameters={"channel_id": "1", "message_id": "2", "emoji_name": "✨"},
    )
    assert target.path.endswith("/%E2%9C%A8/@me")
