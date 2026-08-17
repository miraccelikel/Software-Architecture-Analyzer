"""Mermaid diagrams and the generated codebase tour."""

from __future__ import annotations

from pathlib import Path

import pytest

from archray import Thresholds, build_report
from archray.diagrams import RESERVED, _safe
from archray.parsing import parse_repository
from archray.tour import to_markdown

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "demo_shop"


@pytest.fixture(scope="module")
def report() -> dict:
    files = sorted(DEMO.glob("*.py"))
    return build_report(parse_repository(DEMO, files), Thresholds())


# ------------------------------------------------------------- diyagramlar #
def test_every_diagram_is_produced(report: dict) -> None:
    diagrams = report["diagrams"]
    assert diagrams["classes"].startswith("classDiagram")
    assert diagrams["modules"].startswith("flowchart")


def test_class_diagram_shows_inheritance_and_creation(report: dict) -> None:
    source = report["diagrams"]["classes"]
    assert "PaymentStrategy <|-- LoggedPayment" in source
    assert "OrderService --> MySqlConnection : creates" in source
    assert "<<abstract>>" in source


def test_class_diagram_stays_readable(report: dict) -> None:
    """A diagram with two hundred boxes teaches nobody anything."""
    boxes = report["diagrams"]["classes"].count("  class ")
    assert boxes <= 22


def test_module_diagram_marks_cycles(report: dict) -> None:
    source = report["diagrams"]["modules"]
    assert "classDef cycle" in source
    assert "class " in source and "cycle" in source


@pytest.mark.parametrize("name", sorted(RESERVED)[:6])
def test_reserved_words_are_escaped(name: str) -> None:
    """A module named `graph.py` would silently break the diagram."""
    assert _safe(name) not in RESERVED
    assert _safe(name).startswith("n_")


def test_identifiers_are_mermaid_safe(report: dict) -> None:
    import re
    for source in report["diagrams"].values():
        for line in source.splitlines():
            if line.strip().startswith(("class ", "  class ")) and "{" in line:
                identifier = line.split()[1]
                assert re.fullmatch(r"\w+", identifier)


# -------------------------------------------------------------- kod gezisi #
def test_tour_finds_entry_points_and_foundations(report: dict) -> None:
    tour = report["tour"]
    foundations = {item["file"] for item in tour["foundations"]}
    assert "payments.py" in foundations, "the most depended-upon module is a foundation"
    assert all(item["dependents"] > 0 for item in tour["foundations"])


def test_reading_order_puts_dependencies_first(report: dict) -> None:
    levels = {m["file"]: layer["level"]
              for layer in report["tour"]["layers"] for m in layer["modules"]}
    assert levels["payments.py"] < levels["payment_factory.py"], \
        "read the types a factory produces before the factory"


def test_tour_names_the_abstractions(report: dict) -> None:
    names = {item["name"] for item in report["tour"]["abstractions"]}
    assert "PaymentStrategy" in names


def test_tour_lists_folders_and_danger_zones(report: dict) -> None:
    tour = report["tour"]
    assert tour["folders"] and tour["folders"][0]["loc"] > 0
    assert tour["danger_zones"][0]["findings"] > 0


# ------------------------------------------------------------ markdown output #
def test_markdown_document_is_complete(report: dict) -> None:
    text = to_markdown(report)
    assert text.startswith("# ") and "codebase tour" in text.splitlines()[0]
    for heading in ("## Where to start", "## Reading order", "## Folders",
                    "## Class relationships", "## Module dependencies"):
        assert heading in text
    assert text.count("```mermaid") >= 2
    assert text.count("```") % 2 == 0, "code fences must be balanced"


def test_markdown_survives_an_empty_project() -> None:
    empty = {"tour": {}, "health": {"score": 0, "grade": "F"},
             "summary": {}, "meta": {"version": "0", "generated_at": "2026-01-01"}}
    assert "No tour could be generated" in to_markdown(empty)
