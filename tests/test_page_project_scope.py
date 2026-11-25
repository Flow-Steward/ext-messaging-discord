"""Every page says whether it needs a project, and only connection pages do.

Flow Steward asks for a project before it shows a page that needs one
(manifestPageRequiresProject in the frontend). An explicit ``project_scoped: false``
wins over the extension's project scope in every version of the host, so reference
pages (setup guide, API, coverage, changelog, support) declare it; a page with a
connection form declares ``true``.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PAGES = sorted((ROOT / "ui" / "pages").glob("*.yaml"))


def _needs_project(page: dict) -> bool:
    for component in page.get("components") or []:
        if component.get("type") != "markdown" or component.get("query_id"):
            return True
    return False


def test_there_are_pages() -> None:
    assert PAGES


def test_every_page_declares_its_project_scope_and_only_forms_need_one() -> None:
    wrong = []
    for path in PAGES:
        page = yaml.safe_load(path.read_text(encoding="utf-8"))
        scoped = page.get("project_scoped")
        if not isinstance(scoped, bool) or scoped != _needs_project(page):
            wrong.append(f"{path.name}: project_scoped={scoped!r}")
    assert wrong == []
