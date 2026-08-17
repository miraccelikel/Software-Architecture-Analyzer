"""Mixed-language projects and the structural change report."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from archray import Thresholds, analyze_source
from archray.changes import compare as compare_structure
from archray.changes import materialise
from archray.changes_report import to_markdown
from archray.ingest import Repository, plan

ROOT = Path(__file__).resolve().parents[1]

TS_FILE = """
import { Order } from './order'

export class Cart {
  private items: Order[] = []
  add(order: Order) { this.items.push(order) }
  total(): number { return this.items.length }
}
"""


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture(scope="module")
def polyglot(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("polyglot")
    (root / "backend").mkdir()
    (root / "frontend").mkdir()
    for source in sorted((ROOT / "examples" / "demo_shop").glob("*.py")):
        (root / "backend" / source.name).write_text(source.read_text(encoding="utf-8"),
                                                    encoding="utf-8")
    for source in sorted((ROOT / "examples" / "demo_java" / "com" / "shop").glob("*.java")):
        (root / "backend" / source.name).write_text(source.read_text(encoding="utf-8"),
                                                    encoding="utf-8")
    (root / "frontend" / "cart.ts").write_text(TS_FILE)
    (root / "frontend" / "order.ts").write_text(
        "export class Order { constructor(public id: number) {} }\n")
    return root


# ------------------------------------------------------------ multi-language #
def test_languages_are_detected(polyglot: Path) -> None:
    detected = plan(Repository(root=polyglot, name="poly"))
    assert set(detected) == {"python", "java", "typescript"}


def test_one_report_covers_every_language(polyglot: Path) -> None:
    report = analyze_source(str(polyglot))
    languages = {item["language"]: item for item in report["summary"]["languages"]}
    assert set(languages) == {"python", "java", "typescript"}
    assert languages["python"]["sloc"] > languages["typescript"]["sloc"]
    assert sum(item["modules"] for item in languages.values()) == report["summary"]["modules"]


def test_findings_come_from_all_languages(polyglot: Path) -> None:
    report = analyze_source(str(polyglot))
    files = {finding["file"].rsplit(".", 1)[-1] for finding in report["findings"]}
    assert {"py", "java"} <= files
    patterns = {p["pattern"] for p in report["patterns"]}
    assert "Strategy" in patterns and "Builder" in patterns


def test_modules_carry_their_language(polyglot: Path) -> None:
    report = analyze_source(str(polyglot))
    by_language = {m["language"] for m in report["modules"]}
    assert by_language == {"python", "java", "typescript"}
    nodes = {n["id"]: n["language"] for n in report["graph"]["nodes"]}
    assert any(language == "typescript" for language in nodes.values())


def test_explicit_language_still_narrows(polyglot: Path) -> None:
    report = analyze_source(str(polyglot), language="java")
    assert {item["language"] for item in report["summary"]["languages"]} == {"java"}


def test_header_files_go_to_cpp_when_cpp_exists(tmp_path: Path) -> None:
    (tmp_path / "a.hpp").write_text("class A { public: int f(); };\n")
    (tmp_path / "a.cpp").write_text("#include \"a.hpp\"\nint A::f(){ return 1; }\n")
    (tmp_path / "shared.h").write_text("struct S { int x; };\n")
    detected = plan(Repository(root=tmp_path, name="c"))
    assert "cpp" in detected
    assert any(f.name == "shared.h" for f in detected["cpp"])
    assert "c" not in detected


# ------------------------------------------------------------------ changes #
@pytest.fixture(scope="module")
def edited_repo(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("edited")
    (root / "core.py").write_text(
        "class Engine:\n"
        "    def __init__(self):\n        self.items = []\n"
        "    def run(self, value):\n        return value\n"
        "    def drop(self):\n        self.items.clear()\n"
    )
    (root / "util.py").write_text("def helper(x):\n    return x + 1\n")
    git(root, "init", "-q")
    git(root, "config", "user.email", "a@b.c")
    git(root, "config", "user.name", "Dev")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "baseline")

    # simulate an assistant editing the code: rewrite a method, delete another,
    # add a class, and introduce a dependency
    (root / "core.py").write_text(
        "from util import helper\n\n"
        "class Engine:\n"
        "    def __init__(self):\n        self.items = []\n"
        "    def run(self, value):\n"
        "        if value > 7:\n"
        "            for item in self.items:\n"
        "                if item and helper(item) > 3:\n"
        "                    return item\n"
        "        elif value < 0:\n            return None\n"
        "        return value\n"
        "\n\nclass Cache:\n"
        "    def __init__(self):\n        self.data = {}\n"
        "    def get(self, key):\n        return self.data.get(key)\n"
    )
    return root


@pytest.fixture(scope="module")
def structural_diff(edited_repo: Path) -> dict:
    snapshot = materialise(edited_repo, "HEAD")
    baseline = analyze_source(str(snapshot), thresholds=Thresholds())
    current = analyze_source(str(edited_repo), thresholds=Thresholds())
    return compare_structure(baseline, current, "HEAD")


def test_materialise_does_not_touch_the_working_copy(edited_repo: Path) -> None:
    before = (edited_repo / "core.py").read_text(encoding="utf-8")
    snapshot = materialise(edited_repo, "HEAD")
    assert (snapshot / "core.py").read_text(encoding="utf-8") != before
    assert (edited_repo / "core.py").read_text(encoding="utf-8") == before


def test_rewritten_function_is_detected(structural_diff: dict) -> None:
    modified = {item["qualname"]: item for item in structural_diff["functions"]["modified"]}
    assert "core.Engine.run" in modified
    change = modified["core.Engine.run"]
    assert change["complexity_after"] > change["complexity_before"]
    assert change["complexity_delta"] >= 3


def test_added_and_removed_are_listed(structural_diff: dict) -> None:
    added = {item["qualname"] for item in structural_diff["functions"]["added"]}
    removed = {item["qualname"] for item in structural_diff["functions"]["removed"]}
    assert "core.Cache.get" in added
    assert "core.Engine.drop" in removed
    assert "core.Cache" in {item["qualname"] for item in structural_diff["classes"]["added"]}


def test_new_dependency_edge_is_reported(structural_diff: dict) -> None:
    added = {(edge["source"], edge["target"]) for edge in structural_diff["edges"]["added"]}
    assert ("core", "util") in added


def test_highlights_lead_with_what_matters(structural_diff: dict) -> None:
    kinds = [note["kind"] for note in structural_diff["highlights"]]
    assert "removed_code" in kinds
    assert "new_dependency" in kinds
    warnings = [n for n in structural_diff["highlights"] if n["level"] == "warning"]
    assert warnings and structural_diff["highlights"][0]["level"] == "warning"


def test_unchanged_code_produces_no_noise(edited_repo: Path) -> None:
    """Re-analysing the same tree twice must report nothing."""
    report = analyze_source(str(edited_repo))
    diff = compare_structure(report, report, "HEAD")
    assert diff["functions"]["counts"] == {"added": 0, "removed": 0, "modified": 0}
    assert diff["headline"] == "No structural change."


def test_markdown_review_sheet(structural_diff: dict) -> None:
    report = {"changes": structural_diff, "repository": {"name": "demo"},
              "meta": {"version": "0.1.0"}}
    text = to_markdown(report)
    assert text.startswith("# What changed")
    assert "## Read these first" in text and "## Functions" in text
    assert "core.Engine.run" in text or "run" in text
    assert "`core` → `util`" in text
