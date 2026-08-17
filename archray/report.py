"""Report writers: JSON payload and the self-contained HTML dashboard."""

from __future__ import annotations

import json
from pathlib import Path

TEMPLATE = Path(__file__).parent / "ui" / "dashboard.html"
PLACEHOLDER = "/*__ARCHRAY_DATA__*/null"


def write_json(report: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def render_html(report: dict) -> str:
    template = TEMPLATE.read_text(encoding="utf-8")
    payload = json.dumps(report, ensure_ascii=False).replace("</", "<\\/")
    if PLACEHOLDER not in template:
        raise RuntimeError("The dashboard template has no data placeholder.")
    return template.replace(PLACEHOLDER, payload)


def write_changes(report: dict, path: Path) -> Path:
    """A Markdown review sheet describing what changed structurally."""
    from .changes_report import to_markdown
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_markdown(report), encoding="utf-8")
    return path


def write_pr_comment(report: dict, path: Path) -> Path:
    """A short Markdown comment for a pull request."""
    from .pr_comment import render
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(report), encoding="utf-8")
    return path


def write_sarif(report: dict, path: Path) -> Path:
    """SARIF 2.1.0 — read directly by GitHub Code Scanning and most IDEs."""
    from .sarif import build
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build(report), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_tour(report: dict, path: Path) -> Path:
    """The generated onboarding document, with its Mermaid diagrams inline."""
    from .tour import to_markdown
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_markdown(report), encoding="utf-8")
    return path


def write_html(report: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(report), encoding="utf-8")
    return path
