"""Language front-ends, source excerpts, the class graph and configuration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from archray import Thresholds, build_report
from archray.engine import parse_files
from archray.parsing import parse_repository

pytest.importorskip("tree_sitter_java", reason="tree-sitter grammars are not installed")

ROOT = Path(__file__).resolve().parents[1]
DEMO_PY = ROOT / "examples" / "demo_shop"
DEMO_JAVA = ROOT / "examples" / "demo_java"


def analyse(root: Path, pattern: str, language: str) -> dict:
    files = sorted(root.rglob(pattern))
    return build_report(parse_files(root, files, language), Thresholds())


@pytest.fixture(scope="module")
def java_report() -> dict:
    return analyse(DEMO_JAVA, "*.java", "java")


@pytest.fixture(scope="module")
def python_report() -> dict:
    files = sorted(DEMO_PY.glob("*.py"))
    return build_report(parse_repository(DEMO_PY, files), Thresholds())


# ------------------------------------------------------------------- Java #
def test_java_metrics_are_extracted(java_report: dict) -> None:
    assert java_report["summary"]["classes"] >= 6
    assert java_report["summary"]["functions"] >= 10
    complexities = [f["complexity"] for m in java_report["modules"]
                    for c in m["classes"] for f in [c]]
    assert java_report["health"]["max_complexity"] > 1
    assert complexities


def test_java_rules_fire(java_report: dict) -> None:
    rules = {f["rule"] for f in java_report["findings"]}
    assert "too_many_parameters" in rules
    assert "dip_concrete_dependency" in rules        # new MySqlConnection(...)
    assert "ocp_type_switch" in rules                # instanceof zinciri
    assert "ocp_long_branch_chain" in rules          # if/else if/else if
    assert "magic_number" in rules                   # status == 4


def test_java_patterns(java_report: dict) -> None:
    patterns = {p["pattern"] for p in java_report["patterns"]}
    assert "Builder" in patterns      # chain returning this + build()
    assert "Strategy" in patterns     # interface + 2 implementations + a context class


def test_java_package_becomes_module_name(java_report: dict) -> None:
    modules = {m["module"] for m in java_report["modules"]}
    assert "com.shop.Checkout" in modules
    edges = {(e["source"], e["target"]) for e in java_report["graph"]["edges"]}
    assert any(src.startswith("com.shop") and dst.startswith("com.shop")
               for src, dst in edges), "imports inside a package must resolve"


# ------------------------------------------------------------- TypeScript #
TS_SOURCE = """
import { Logger } from './logger'

export interface Repository {
  find(id: number): string
}

export class SqlRepository implements Repository {
  private cache = new Map<number, string>()
  find(id: number): string {
    if (id === 42) { return 'cached' }
    return String(id)
  }
}

export const handle = (value: unknown, retries: number) => {
  if (typeof value === 'string') { return value }
  if (value instanceof Error) { return value.message }
  if (retries > 7) { return 'giving up' }
  return null
}
"""


def test_typescript_frontend(tmp_path: Path) -> None:
    (tmp_path / "logger.ts").write_text("export class Logger { log(m: string) {} }\n")
    (tmp_path / "service.ts").write_text(TS_SOURCE)
    report = analyse(tmp_path, "*.ts", "typescript")

    names = {c["name"] for m in report["modules"] for c in m["classes"]}
    assert {"Repository", "SqlRepository", "Logger"} <= names

    functions = {f["name"] for m in report["modules"] for f in m["functions"]}
    assert "handle" in functions, "arrow functions (const f = () => {}) must be captured"

    handle = next(f for m in report["modules"] for f in m["functions"] if f["name"] == "handle")
    assert handle["complexity"] >= 4
    assert not any(m["parse_error"] for m in report["modules"])


# --------------------------------------------------------- kaynak kesiti #
def test_every_finding_carries_its_source(python_report: dict) -> None:
    for finding in python_report["findings"]:
        snippet = finding["snippet"]
        assert snippet["lines"], f"no excerpt for {finding['rule']}"
        assert snippet["start"] <= finding["line"]
        assert finding["line"] < snippet["start"] + len(snippet["lines"])


def test_snippet_focus_line_matches_source(python_report: dict) -> None:
    god = next(f for f in python_report["findings"] if f["rule"] == "god_class")
    snippet = god["snippet"]
    focused = snippet["lines"][god["line"] - snippet["start"]]
    assert "class OrderService" in focused


def test_snippet_is_bounded(python_report: dict) -> None:
    assert all(len(f["snippet"]["lines"]) <= 14 for f in python_report["findings"])


# -------------------------------------------------------------- class graph #
def test_class_graph_edges(python_report: dict) -> None:
    graph = python_report["graph"]
    edges = {(e["source"].split(".")[-1], e["target"].split(".")[-1]): e["kind"]
             for e in graph["class_edges"]}
    assert edges[("LoggedPayment", "PaymentStrategy")] == "extends"
    assert edges[("OrderService", "MySqlConnection")] == "creates"
    assert len(graph["class_nodes"]) == python_report["summary"]["classes"]


def test_class_graph_finds_its_own_cycle(python_report: dict) -> None:
    cycles = python_report["graph"]["class_cycles"]
    assert any({"audit.AuditTrail", "legacy_order_service.OrderService"} <= set(c)
               for c in cycles)


def test_class_findings_are_attributed(python_report: dict) -> None:
    nodes = {n["id"].split(".")[-1]: n for n in python_report["graph"]["class_nodes"]}
    assert nodes["OrderService"]["findings"] > 5
    assert nodes["InvoiceBuilder"]["findings"] == 0


# ---------------------------------------------------------------- ayarlar #
def test_thresholds_from_file(tmp_path: Path) -> None:
    config = tmp_path / "archray.json"
    config.write_text(json.dumps({"thresholds": {"long_method_loc": 5}}))
    assert Thresholds.load(config).long_method_loc == 5


def test_unknown_threshold_key_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "bad.json"
    config.write_text(json.dumps({"god_clas_loc": 100}))
    with pytest.raises(ValueError, match="Unknown config key"):
        Thresholds.load(config)


def test_lower_threshold_produces_more_findings(tmp_path: Path) -> None:
    files = sorted(DEMO_PY.glob("*.py"))
    modules = parse_repository(DEMO_PY, files)
    strict = build_report(modules, Thresholds(long_method_loc=15))
    default = build_report(modules, Thresholds())
    count = lambda r: sum(1 for f in r["findings"] if f["rule"] == "long_method")
    assert count(strict) > count(default)


# --------------------------------------------------------------------- C# #
DEMO_CSHARP = ROOT / "examples" / "demo_csharp"
DEMO_CPP = ROOT / "examples" / "demo_cpp"
DEMO_C = ROOT / "examples" / "demo_c"


@pytest.fixture(scope="module")
def csharp_report() -> dict:
    return analyse(DEMO_CSHARP, "*.cs", "csharp")


def test_csharp_namespace_becomes_module_name(csharp_report: dict) -> None:
    modules = {m["module"] for m in csharp_report["modules"]}
    assert "Shop.Payments.Payments" in modules
    assert "Shop.Orders.OrderService" in modules


def test_csharp_rules(csharp_report: dict) -> None:
    rules = {f["rule"] for f in csharp_report["findings"]}
    assert "dip_concrete_dependency" in rules      # new SqlConnection()
    assert "ocp_type_switch" in rules              # order is string / order is int
    assert "ocp_long_branch_chain" in rules
    assert "srp_low_cohesion" in rules             # order fields and report fields never meet
    assert "dead_private_method" in rules          # _UnusedHelper


def test_csharp_constructor_does_not_hide_low_cohesion(csharp_report: dict) -> None:
    """A constructor touches every field, so it must stay out of LCOM4."""
    service = next(c for m in csharp_report["modules"] for c in m["classes"]
                   if c["name"] == "OrderService")
    assert service["lcom4"] == 2


def test_csharp_strategy_needs_the_field_type(csharp_report: dict) -> None:
    """Checkout holds a field typed IPaymentStrategy, so this is a full Strategy."""
    strategy = next(p for p in csharp_report["patterns"] if p["pattern"] == "Strategy")
    assert "Checkout" in " ".join(strategy["evidence"])
    assert strategy["confidence"] > 0.8


# -------------------------------------------------------------------- C++ #
@pytest.fixture(scope="module")
def cpp_report() -> dict:
    return analyse(DEMO_CPP, "*.*", "cpp")


def test_cpp_header_and_source_are_one_module(cpp_report: dict) -> None:
    modules = {m["module"] for m in cpp_report["modules"]}
    assert modules == {"payment", "order_service", "infrastructure"}


def test_cpp_out_of_line_definition_reaches_its_class(cpp_report: dict) -> None:
    """`OrderService::process` is declared in the header and defined in the .cpp."""
    service = next(c for m in cpp_report["modules"] for c in m["classes"]
                   if c["name"] == "OrderService")
    assert service["methods"] == 3
    assert service["loc"] > 25, "a class must be measured with its method bodies"

    dip = [f for f in cpp_report["findings"] if f["rule"] == "dip_concrete_dependency"]
    assert {f["metrics"]["depends_on"].split(".")[-1] for f in dip} == \
        {"MySqlConnection", "FileLogger"}


def test_cpp_pure_virtual_is_an_interface(cpp_report: dict) -> None:
    base = next(c for m in cpp_report["modules"] for c in m["classes"]
                if c["name"] == "PaymentStrategy")
    assert base["is_abstract"]
    assert "Strategy" in {p["pattern"] for p in cpp_report["patterns"]}


def test_cpp_snippets_survive_the_merge(cpp_report: dict) -> None:
    """A finding in the .cpp must still carry its source excerpt."""
    from_source = [f for f in cpp_report["findings"] if f["file"].endswith(".cpp")]
    assert from_source
    assert all(f["snippet"]["lines"] for f in from_source)


# ---------------------------------------------------------------------- C #
@pytest.fixture(scope="module")
def c_report() -> dict:
    return analyse(DEMO_C, "*.*", "c")


def test_c_has_functions_but_no_methods(c_report: dict) -> None:
    functions = {f["name"] for m in c_report["modules"] for f in m["functions"]}
    assert {"process_order", "count_pending", "count_high_value"} <= functions
    assert all(c["methods"] == 0 for m in c_report["modules"] for c in m["classes"]), \
        "structs in C have no methods"


def test_c_typedef_struct_is_named(c_report: dict) -> None:
    structs = {c["name"] for m in c_report["modules"] for c in m["classes"]}
    assert {"order_t", "order_list_t"} <= structs


def test_c_includes_build_the_graph(c_report: dict) -> None:
    edges = {(e["source"], e["target"]) for e in c_report["graph"]["edges"]}
    assert ("orders", "shop") in edges and ("report", "shop") in edges


def test_c_system_headers_are_not_dependencies(c_report: dict) -> None:
    """#include <string.h> is not a project dependency."""
    targets = {e["target"] for e in c_report["graph"]["edges"]}
    assert not any(t in ("string", "stddef") for t in targets)


def test_c_rules_and_clones(c_report: dict) -> None:
    rules = {f["rule"] for f in c_report["findings"]}
    assert {"high_cyclomatic_complexity", "magic_number", "too_many_parameters",
            "deep_nesting", "duplicate_code"} <= rules
    clone = next(f for f in c_report["findings"] if f["rule"] == "duplicate_code")
    assert clone["metrics"]["copies"] == 2
