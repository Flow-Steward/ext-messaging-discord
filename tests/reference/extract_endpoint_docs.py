#!/usr/bin/env python3
"""Extract each endpoint's name, first paragraph and parameter descriptions from the
Discord API documentation (discord-api-docs, pinned commit), for step names, step
descriptions, field help and the grouping of the UI pages.

Run with ``python3 -I tests/reference/extract_endpoint_docs.py <developers dir>`` on an
unpacked copy of the pinned commit's ``developers`` folder; it writes
``tests/reference/discord-endpoint-docs.json`` with the SHA-256 of every page it read.
The pages are data: nothing in them is executed.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

COMMIT = "9b737ec51ee8d5076af0565d209a9adf8f590a27"
OUT = Path(__file__).resolve().parent / "discord-endpoint-docs.json"

_HEADING = re.compile(r"^##\s+(?P<title>[^#\n].*?)\s*$")
_ROUTE = re.compile(r'<Route method="(?P<method>[A-Z]+)">(?P<path>.*?)</Route>')
_PLACEHOLDER = re.compile(r"\[\\\{([^\\]+)\\\}\]\([^)]*\)|\\\{([^\\]+)\\\}|\{([^}]+)\}")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_CALLOUT = re.compile(r"^<(Danger|Warning|Info|Callout|Note|Tip)\b[^>]*>$")
_TABLE_HEAD = re.compile(r"^######\s+(?P<name>.+?)\s*$")


def plain(text: str) -> str:
    """Markdown links and emphasis reduced to their text, spaces collapsed."""
    text = _LINK.sub(r"\1", text)
    text = text.replace("\\*", "*").replace("\\_", "_").replace("\\", "")
    text = re.sub(r"`([^`]*)`", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def normalized(path: str) -> str:
    """The route with every placeholder as ``{}`` and links removed."""
    path = _PLACEHOLDER.sub("{}", path.replace("\\_", "_"))
    return _LINK.sub(r"\1", path).strip()


def _table(lines: list[str], start: int) -> tuple[dict[str, str], int]:
    """A markdown table's first and last column (name -> description) from ``start``."""
    rows: dict[str, str] = {}
    i = start
    while i < len(lines) and not lines[i].lstrip().startswith("|"):
        if lines[i].startswith("#") or _ROUTE.search(lines[i]):
            return rows, i
        i += 1
    column = -1
    header = True
    while i < len(lines) and lines[i].lstrip().startswith("|"):
        cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        if header:
            names = [plain(c).lower() for c in cells]
            column = names.index("description") if "description" in names else len(cells) - 1
            header = False
            i += 1
            continue
        if set(lines[i].replace("|", "").strip()) <= {"-", ":", " "}:
            i += 1
            continue
        name = plain(cells[0]).rstrip("?*").strip()
        if name and len(cells) > column:
            rows[name] = plain(cells[column])
        i += 1
    return rows, i


def extract(root: Path) -> dict:
    endpoints: dict[str, dict] = {}
    pages: dict[str, str] = {}
    for page in sorted(root.rglob("*.mdx")):
        if True:
            raw = page.read_bytes()
            text = raw.decode("utf-8")
            lines = text.splitlines()
            rel = "developers/" + page.relative_to(root).as_posix()
            found = False
            for i, line in enumerate(lines):
                route = _ROUTE.search(line)
                if not route:
                    continue
                title = ""
                for back in range(i - 1, max(i - 6, -1), -1):
                    heading = _HEADING.match(lines[back])
                    if heading:
                        title = plain(heading.group("title"))
                        break
                if not title:
                    continue
                key = f"{route.group('method')} {normalized(route.group('path'))}"
                paragraph: list[str] = []
                callout: list[str] = []
                j = i + 1
                while j < len(lines):
                    line = lines[j].strip()
                    opened = _CALLOUT.match(line)
                    if not line or line.startswith("<ManualAnchor"):
                        j += 1
                    elif opened:
                        # A notice box (<Danger>, <Warning>, <Info>) before the text:
                        # kept only when the endpoint has no paragraph of its own.
                        tag = opened.group(1)
                        j += 1
                        while j < len(lines) and f"</{tag}>" not in lines[j]:
                            callout.append(lines[j])
                            j += 1
                        j += 1
                    else:
                        break
                while (
                    j < len(lines)
                    and lines[j].strip()
                    and not lines[j].startswith(("#", "<", "|", ">"))
                ):
                    paragraph.append(lines[j])
                    j += 1
                if not paragraph:
                    paragraph = callout
                params: dict[str, dict[str, str]] = {}
                k = j
                while k < len(lines) and not lines[k].startswith("## "):
                    head = _TABLE_HEAD.match(lines[k])
                    if head:
                        kind = head.group("name").lower()
                        rows, k = _table(lines, k + 1)
                        if "query" in kind:
                            params.setdefault("query", {}).update(rows)
                        elif "json" in kind or "form" in kind or "params" in kind:
                            params.setdefault("body", {}).update(rows)
                        continue
                    k += 1
                entry = {
                    "title": title,
                    "description": plain(" ".join(paragraph)),
                    "page": rel,
                    "params": params,
                }
                # One route can be documented twice (an interaction followup is a webhook
                # execution): the resource's own page wins.
                if key not in endpoints or (
                    "/resources/" in rel and "/resources/" not in endpoints[key]["page"]
                ):
                    endpoints[key] = entry
                found = True
            if found:
                pages[rel] = hashlib.sha256(raw).hexdigest()
    return {
        "repository": "https://github.com/discord/discord-api-docs",
        "commit": COMMIT,
        "pages": pages,
        "endpoints": dict(sorted(endpoints.items())),
    }


def main() -> int:
    data = extract(Path(sys.argv[1]))
    OUT.write_text(json.dumps(data, indent=1, sort_keys=False, ensure_ascii=False) + "\n")
    print(f"{len(data['endpoints'])} endpoints from {len(data['pages'])} pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
