"""Every detector must fire on the sample project."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from archray import Thresholds, build_report
from archray.parsing import FunctionParser, parse_repository
from archray.report import render_html
from archray.solid import compute_lcom4

DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo_shop"


@pytest.fixture(scope="module")
def report() -> dict:
    files = sorted(DEMO.glob("*.py"))
    modules = parse_repository(DEMO, files)
    return build_report(modules, Thresholds())


def rules(report: dict) -> set[str]:
    return {finding["rule"] for finding in report["findings"]}


def patterns(report: dict) -> set[str]:
    return {match["pattern"] for match in report["patterns"]}


# --------------------------------------------------------------- metrikler #
@pytest.mark.parametrize("source,expected", [
    ("def f():\n    pass\n", 1),
    ("def f(x):\n    if x:\n        return 1\n    return 0\n", 2),
    ("def f(x):\n    if x > 0 and x < 10:\n        return 1\n    return 0\n", 3),
    ("def f(xs):\n    return [x for x in xs if x]\n", 3),
    ("def f(x):\n    for i in x:\n        while i:\n            i -= 1\n", 3),
    ("def f(x):\n    try:\n        g()\n    except ValueError:\n        pass\n"
     "    except KeyError:\n        pass\n", 3),
])
def test_cyclomatic_complexity(source: str, expected: int) -> None:
    node = ast.parse(source).body[0]
    assert FunctionParser(node, "t.py").parse().complexity == expected


def test_nesting_and_parameters() -> None:
    node = ast.parse(
        "def f(a, b, c, d, e, f_, g):\n"
        "    if a:\n        for i in b:\n            while c:\n                if d:\n"
        "                    return i\n"
    ).body[0]
    info = FunctionParser(node, "t.py").parse()
    assert len(info.params) == 7
    assert info.max_nesting >= 4


def test_lcom4_splits_disjoint_responsibilities() -> None:
    tree = ast.parse(
        "class C:\n"
        "    def __init__(self):\n        self.a = 1\n        self.b = 2\n"
        "    def touch_a(self):\n        return self.a\n"
        "    def also_a(self):\n        return self.a + 1\n"
        "    def touch_b(self):\n        return self.b\n"
    )
    from archray.parsing import ModuleParser
    parser = ModuleParser.__new__(ModuleParser)
    parser.module_name, parser.rel_path = "m", "m.py"
    cls = parser._parse_class(tree.body[0])
    components, groups = compute_lcom4(cls)
    assert components == 2
    assert sorted(len(g) for g in groups) == [1, 2]


# ------------------------------------------------------------- code smells #
def test_code_smells_detected(report: dict) -> None:
    found = rules(report)
    for rule in ("god_class", "long_method", "too_many_parameters",
                 "magic_number", "deep_nesting", "high_cyclomatic_complexity"):
        assert rule in found, f"{rule} tespit edilmedi"


def test_god_class_points_at_order_service(report: dict) -> None:
    god = [f for f in report["findings"] if f["rule"] == "god_class"]
    assert len(god) == 1
    assert god[0]["symbol"] == "OrderService"
    assert god[0]["metrics"]["methods"] > 20
    assert god[0]["metrics"]["loc"] > 500


# ------------------------------------------------------------------ SOLID #
def test_all_five_solid_principles_fire(report: dict) -> None:
    found = rules(report)
    assert "srp_low_cohesion" in found
    assert {"ocp_type_switch", "ocp_long_branch_chain"} & found
    assert "lsp_refused_bequest" in found
    assert "dip_concrete_dependency" in found


def test_dip_names_the_concrete_dependency(report: dict) -> None:
    dip = [f for f in report["findings"] if f["rule"] == "dip_concrete_dependency"]
    depends = {f["metrics"]["depends_on"].split(".")[-1] for f in dip}
    assert {"MySqlConnection", "SmtpMailer", "FileLogger"} <= depends


def test_factory_is_not_reported_as_dip_violation(report: dict) -> None:
    """Factories creating concrete types is their job, not a violation."""
    offenders = {f["symbol"] for f in report["findings"]
                 if f["rule"] == "dip_concrete_dependency"}
    assert not any(symbol.startswith("PaymentFactory") for symbol in offenders)


# --------------------------------------------------------------- desenler #
def test_design_patterns_detected(report: dict) -> None:
    found = patterns(report)
    for pattern in ("Singleton", "Strategy", "Factory", "Builder", "Observer", "Decorator"):
        assert pattern in found, f"{pattern} tespit edilmedi"


def test_pattern_confidence_is_bounded(report: dict) -> None:
    assert all(0 < m["confidence"] <= 1 for m in report["patterns"])


# ----------------------------------------------------------------- grafik #
def test_circular_dependency_found_once(report: dict) -> None:
    cycles = report["graph"]["cycles"]
    assert len(cycles) == 1
    assert {"audit", "legacy_order_service"} <= set(cycles[0])
    reported = [f for f in report["findings"] if f["rule"] == "circular_dependency"]
    assert len(reported) == 1, "each cycle is reported exactly once"


def test_graph_nodes_carry_coupling_metrics(report: dict) -> None:
    nodes = {n["id"]: n for n in report["graph"]["nodes"]}
    assert nodes["payments"]["fan_in"] > 0
    assert all(0 <= n["instability"] <= 1 for n in nodes.values())


# ------------------------------------------------------------------ rapor #
def test_report_shape(report: dict) -> None:
    assert 0 <= report["health"]["score"] <= 100
    assert report["health"]["grade"] in "ABCDF"
    assert len(report["top_debt"]) == 5
    assert report["top_debt"][0]["severity"] == "critical"
    assert report["summary"]["classes"] > 10


def test_html_dashboard_embeds_data(report: dict) -> None:
    html = render_html(report)
    assert "__ARCHRAY_DATA__" not in html
    assert '"grade"' in html and "<canvas" in html
