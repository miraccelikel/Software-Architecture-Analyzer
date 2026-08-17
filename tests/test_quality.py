"""Duplicate code, dead private methods, suppression and the findings diff."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from archray import Thresholds, analyze_source, build_report
from archray.compare import compare
from archray.parsing import parse_repository, structural_fingerprint
from archray.suppression import _suppressed_rules

ORIGINAL = """
def parse_user(raw):
    result = {}
    for key in raw:
        if key == 3:
            result[key] = raw[key]
        elif key in result:
            result[key] = raw[key].strip()
        else:
            result[key] = None
    return result
"""

RENAMED_COPY = """
def parse_order(payload):
    output = {}
    for field in payload:
        if field == 91:
            output[field] = payload[field]
        elif field in output:
            output[field] = payload[field].strip()
        else:
            output[field] = None
    return output
"""

DIFFERENT = """
def total(items):
    return sum(item.price for item in items if item.active)
"""


def fingerprint_of(source: str) -> tuple[str, int]:
    return structural_fingerprint(ast.parse(source).body[0])


def analyse_dir(path: Path, thresholds: Thresholds | None = None) -> dict:
    files = sorted(path.rglob("*.py"))
    return build_report(parse_repository(path, files), thresholds or Thresholds())


# ------------------------------------------------------------- kopya kod #
def test_renaming_does_not_hide_a_copy() -> None:
    assert fingerprint_of(ORIGINAL)[0] == fingerprint_of(RENAMED_COPY)[0]


def test_different_logic_has_a_different_fingerprint() -> None:
    assert fingerprint_of(ORIGINAL)[0] != fingerprint_of(DIFFERENT)[0]


def test_literal_type_change_breaks_the_match() -> None:
    """3 and 91 are the same shape; 3 and 'x' are not."""
    with_text = RENAMED_COPY.replace("== 91", "== 'x'")
    assert fingerprint_of(ORIGINAL)[0] != fingerprint_of(with_text)[0]


def test_clone_group_is_reported_once(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(ORIGINAL + DIFFERENT)
    (tmp_path / "b.py").write_text(RENAMED_COPY)
    report = analyse_dir(tmp_path)

    clones = [f for f in report["findings"] if f["rule"] == "duplicate_code"]
    assert len(clones) == 1, "one finding per clone group"
    assert clones[0]["metrics"]["copies"] == 2
    assert clones[0]["metrics"]["files"] == 2
    assert "b.py" in clones[0]["message"]


def test_trivial_bodies_are_not_clones(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "def get_name(self):\n    return self.name\n\n"
        "def get_city(self):\n    return self.city\n"
    )
    report = analyse_dir(tmp_path)
    assert not [f for f in report["findings"] if f["rule"] == "duplicate_code"]


def test_generated_god_class_copies_are_caught() -> None:
    demo = Path(__file__).resolve().parents[1] / "examples" / "demo_shop"
    report = analyse_dir(demo)
    clones = [f for f in report["findings"] if f["rule"] == "duplicate_code"]
    assert clones and max(c["metrics"]["copies"] for c in clones) >= 5


# ---------------------------------------------------------------- dead code #
def test_uncalled_private_method_is_flagged(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text(
        "class Service:\n"
        "    def __init__(self):\n        self.items = []\n"
        "    def run(self):\n        return self._used()\n"
        "    def _used(self):\n        return len(self.items)\n"
        "    def _forgotten(self):\n        return self.items[0]\n"
    )
    dead = {f["symbol"] for f in analyse_dir(tmp_path)["findings"]
            if f["rule"] == "dead_private_method"}
    assert dead == {"Service._forgotten"}


def test_constructor_is_never_dead_code(tmp_path: Path) -> None:
    (tmp_path / "s.py").write_text(
        "class Single:\n"
        "    _instance = None\n"
        "    def __init__(self):\n        self.value = 1\n"
        "    def get(self):\n        return self.value\n"
    )
    dead = [f for f in analyse_dir(tmp_path)["findings"]
            if f["rule"] == "dead_private_method"]
    assert not dead


# -------------------------------------------------------------- susturma #
@pytest.mark.parametrize("line,expected", [
    ("x = 1", None),
    ("if x == 42:  # archray: ignore", set()),
    ("if x == 42:  # archray: ignore[magic_number]", {"magic_number"}),
    ("# archray: ignore[magic_number, long_method]", {"magic_number", "long_method"}),
])
def test_marker_parsing(line: str, expected) -> None:
    assert _suppressed_rules(line) == expected


def test_inline_suppression(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text(
        "def f(x):\n    if x == 4711:  # archray: ignore[magic_number]\n        return 1\n"
        "    return 0\n\n"
        "def g(x):\n    if x == 8123:\n        return 1\n    return 0\n"
    )
    report = analyze_source(str(tmp_path))
    magic = [f for f in report["findings"] if f["rule"] == "magic_number"]
    assert [f["symbol"] for f in magic] == ["g"]
    assert report["summary"]["suppressed"] == 1


def test_rule_can_be_disabled_from_config(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("def f(x):\n    if x == 4711:\n        return 1\n    return 0\n")
    report = analyze_source(str(tmp_path), thresholds=Thresholds(ignore_rules=["magic_number"]))
    assert not [f for f in report["findings"] if f["rule"] == "magic_number"]


def test_excluded_paths_are_not_parsed(tmp_path: Path) -> None:
    (tmp_path / "keep.py").write_text("def f(x):\n    if x == 4711:\n        return 1\n    return 0\n")
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "pb.py").write_text("def g(x):\n    if x == 9999:\n        return 1\n    return 0\n")

    report = analyze_source(str(tmp_path), thresholds=Thresholds(exclude_paths=["generated/*"]))
    assert {m["path"] for m in report["modules"]} == {"keep.py"}


# --------------------------------------------------------------- comparison #
def _report_with(findings: list[dict], score: float) -> dict:
    return {"findings": findings, "health": {"score": score, "grade": "C"},
            "meta": {"generated_at": "2026-01-01T00:00:00"}, "repository": {"name": "x"}}


def finding(rule: str, symbol: str, severity: str = "major", **metrics) -> dict:
    return {"rule": rule, "file": "a.py", "line": 1, "symbol": symbol,
            "severity": severity, "title": rule, "metrics": metrics}


def test_diff_detects_new_and_fixed() -> None:
    old = _report_with([finding("god_class", "A"), finding("long_method", "A.run")], 70.0)
    new = _report_with([finding("god_class", "A"), finding("magic_number", "A.calc")], 72.5)
    diff = compare(old, new)

    assert diff["new_count"] == 1 and diff["fixed_count"] == 1
    assert diff["new"][0]["rule"] == "magic_number"
    assert diff["fixed"][0]["rule"] == "long_method"
    assert diff["score_delta"] == 2.5


def test_moving_code_is_not_a_change() -> None:
    old = _report_with([finding("god_class", "A")], 70.0)
    moved = _report_with([{**finding("god_class", "A"), "line": 400}], 70.0)
    diff = compare(old, moved)
    assert diff["new_count"] == 0 and diff["fixed_count"] == 0
    assert diff["verdict"] == "No architectural difference."


def test_repeated_findings_on_one_symbol_are_counted_separately() -> None:
    """Fixing two of three concrete dependencies is two improvements, not one."""
    make = lambda dep: finding("dip_concrete_dependency", "A.__init__", depends_on=dep)
    old = _report_with([make("Db"), make("Mailer"), make("Logger")], 60.0)
    new = _report_with([make("Db")], 68.0)
    diff = compare(old, new)
    assert diff["fixed_count"] == 2 and diff["new_count"] == 0


def test_info_findings_are_ignored_in_the_diff() -> None:
    old = _report_with([], 80.0)
    new = _report_with([finding("singleton_global_state", "S", severity="info")], 80.0)
    assert compare(old, new)["new_count"] == 0


def test_comparison_lands_in_the_report(tmp_path: Path) -> None:
    source = tmp_path / "m.py"
    source.write_text("def f(x):\n    return x\n")
    baseline = analyze_source(str(tmp_path))
    source.write_text("def f(x, a, b, c, d, e, g):\n    return x\n")
    current = analyze_source(str(tmp_path))

    diff = compare(baseline, current)
    assert diff["new_count"] == 1
    assert diff["new"][0]["rule"] == "too_many_parameters"
    assert json.dumps(diff)  # must be embeddable in the report
