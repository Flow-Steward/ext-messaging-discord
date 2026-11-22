"""Generate the Discord v10 route registry from the vendored OpenAPI document."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "tests/reference/discord-openapi.json"
REGISTRY = ROOT / "runtime/rest_routes.json"
METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "trace"})
PATH_PARAMETER = re.compile(r"\{([a-zA-Z0-9_]+)\}")
SECRET_PATH_PARAMETERS = frozenset({"interaction_token", "webhook_token"})


def build_routes(spec: dict[str, Any]) -> dict[str, Any]:
    routes: dict[str, Any] = {}
    for path, item in sorted(spec["paths"].items()):
        for method in sorted(METHODS.intersection(item)):
            operation = item[method]
            operation_id = operation["operationId"]
            if operation_id in routes:
                raise ValueError(f"Duplicate operation ID: {operation_id}")
            parameters = {
                (parameter["in"], parameter["name"]): parameter
                for parameter in [*item.get("parameters", []), *operation.get("parameters", [])]
            }
            path_names = PATH_PARAMETER.findall(path)
            if set(path_names) != {name for location, name in parameters if location == "path"}:
                raise ValueError(f"Path parameter mismatch: {operation_id}")
            if any(location not in {"path", "query"} for location, _ in parameters):
                raise ValueError(f"Unrecognized parameter location: {operation_id}")
            body = operation.get("requestBody", {})
            routes[operation_id] = {
                "method": method.upper(),
                "path": path,
                "path_parameters": path_names,
                "secret_path_parameters": sorted(SECRET_PATH_PARAMETERS.intersection(path_names)),
                "query_parameters": sorted(
                    name for location, name in parameters if location == "query"
                ),
                "required_query_parameters": sorted(
                    name
                    for (location, name), p in parameters.items()
                    if location == "query" and p.get("required")
                ),
                "security": operation.get("security", spec.get("security", [])),
                "request_media_types": sorted(body.get("content", {})),
                "request_body_required": bool(body.get("required", False)),
                "success_statuses": sorted(
                    int(code) for code in operation["responses"] if code.startswith("2")
                ),
            }
    return routes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = (
        json.dumps(build_routes(json.loads(SPEC.read_text())), indent=2, sort_keys=True) + "\n"
    )
    if args.check:
        if REGISTRY.read_text() != expected:
            raise SystemExit("runtime/rest_routes.json is out of date")
    else:
        REGISTRY.write_text(expected)


if __name__ == "__main__":
    main()
