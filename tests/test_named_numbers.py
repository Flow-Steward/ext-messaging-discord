"""Limits are named: no bare number in the places where a limit is set or shown.

Inside a function of ``runtime/`` (constants are defined at module level, each with the
source of its value), a number larger than 2 may not be:

- the value of a limit argument (``max_length``, ``max_items``, ``most``, ``default``,
  ``high``, ``limit``, ``maximum``);
- the length given to ``safe_text``;
- a slice bound (``items[:5]``);
- compared with a ``len(...)``;
- an operand of arithmetic (``remaining + 15``, ``1024 * 1024``).

A message never writes a size by hand ("20 MB"): it is formed from the constant the
check uses, so the number shown and the limit never differ.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1] / "runtime"
LIMIT_ARGUMENTS = frozenset(
    {"max_length", "max_items", "most", "default", "high", "limit", "maximum"}
)
#: 0, 1 and 2 (halving, a pair) are not limits.
SMALL = 2
SIZE_IN_TEXT = re.compile(r"\b\d+(?:\.\d+)?\s?(?:KB|MB|GB|KiB|MiB|GiB)\b")


def _big(node: ast.AST | None) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
        and node.value > SMALL
    )


def _docstrings(tree: ast.AST) -> set[int]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                found.add(id(body[0].value))
    return found


def _findings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = _docstrings(tree)
    out: list[str] = []

    def where(node: ast.AST, what: str) -> None:
        out.append(f"{path.name}:{getattr(node, 'lineno', 0)} {what}")

    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(function):
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if keyword.arg in LIMIT_ARGUMENTS and _big(keyword.value):
                        where(node, f"{keyword.arg}= is a bare number")
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if name == "safe_text" and len(node.args) > 1 and _big(node.args[1]):
                    where(node, "safe_text length is a bare number")
            elif isinstance(node, ast.Slice):
                if _big(node.lower) or _big(node.upper):
                    where(node, "slice bound is a bare number")
            elif isinstance(node, ast.Compare):
                sides = [node.left, *node.comparators]
                has_len = any(
                    isinstance(s, ast.Call) and getattr(s.func, "id", None) == "len" for s in sides
                )
                if has_len and any(_big(s) for s in sides):
                    where(node, "len() compared with a bare number")
            elif isinstance(node, ast.BinOp) and (_big(node.left) or _big(node.right)):
                where(node, "arithmetic with a bare number")
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            size = SIZE_IN_TEXT.search(node.value)
            if size is not None:
                where(node, f"size written in a text: {size.group(0)}")
    return out


def test_limits_are_named_constants() -> None:
    findings = [f for path in sorted(RUNTIME.glob("*.py")) for f in _findings(path)]
    assert findings == []
