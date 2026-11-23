"""Keep one step's whole response inside what the Flow Steward 0.9.x host accepts.

The host walks every value of an extension response for reflected secrets and fails
closed past its traversal limits. This module keeps the complete response envelope
(``ok``, ``result`` with every output, the effect facts) inside tighter limits:

- serialized size at most ``MAX_SERIALIZED_BYTES`` (3,500,000 bytes);
- at most ``MAX_NODES`` (2,000,000) values and keys;
- containers nested at most ``MAX_DEPTH`` (48) levels below the envelope.

It always measures the envelope exactly as ``main.py`` writes it.
"""

from __future__ import annotations

import json
from typing import Any

MAX_NODES = 2_000_000
MAX_DEPTH = 48
MAX_SERIALIZED_BYTES = 3_500_000
#: Room kept for one more warning when a list stops early.
WARNING_ROOM = 400


def written_size(value: Any) -> int:
    return len(json.dumps(value).encode("utf-8"))


def measure(value: Any) -> tuple[int, int, int]:
    """Nodes (values and keys), container depth below ``value`` and written bytes."""
    nodes = deepest = 0
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        node, level = stack.pop()
        nodes += 1
        if isinstance(node, dict):
            deepest = max(deepest, level)
            nodes += len(node)
            stack.extend((nested, level + 1) for nested in node.values())
        elif isinstance(node, (list, tuple)):
            deepest = max(deepest, level)
            stack.extend((nested, level + 1) for nested in node)
    return nodes, deepest, written_size(value)


def fits(envelope: Any, *, room: int = 0) -> bool:
    nodes, deepest, size = measure(envelope)
    return nodes <= MAX_NODES and deepest <= MAX_DEPTH and size + room <= MAX_SERIALIZED_BYTES
