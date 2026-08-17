"""Git history analysis, SARIF output and the pull request comment."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from archray import Thresholds, analyze_source, build_report
from archray import history as history_mod
from archray.parsing import parse_repository
from archray.pr_comment import render
from archray.sarif import build as build_sarif

COMPLEX = """
def handle(value, mode, retries, extra, flag, note):
    total = 0
    for item in value:
        if mode == 4711:
            total += 1
        elif mode == 8123:
            total -= 1
        elif flag and retries > 7:
            for inner in item:
                if inner:
                    total += 2
    return total
"""


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


@pytest.fixture(scope="module")
def repo(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("history")
    git(root, "init", "-q")
    git(root, "config", "user.email", "a@example.com")
    git(root, "config", "user.name", "Ada")

    (root / "core.py").write_text(COMPLEX)
    (root / "helper.py").write_text("def helper():\n    return 1\n")
    (root / "lonely.py").write_text("def lonely():\n    return 2\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "ilk")

    # core.py and helper.py always change together; lonely.py never changes
    for index in range(6):
        (root / "core.py").write_text(COMPLEX + f"\n# revizyon {index}\n")
        (root / "helper.py").write_text(f"def helper():\n    return {index}\n")
        git(root, "add", "-A")
        if index == 3:
            git(root, "config", "user.name", "Linus")
        git(root, "commit", "-qm", f"change {index}")
    return root


@pytest.fixture(scope="module")
def report(repo: Path) -> dict:
    return analyze_source(str(repo), history_commits=50)


# -------------------------------------------------------------------- history #
def test_history_is_collected(report: dict) -> None:
    evolution = report["history"]
    assert evolution["commits_scanned"] == 7
    assert evolution["authors"] == 2


def test_change_frequency_ranks_the_volatile_file(report: dict) -> None:
    hotspots = {h["file"]: h for h in report["history"]["hotspots"]}
    assert hotspots["core.py"]["revisions"] == 7
    assert hotspots["core.py"]["risk"] > hotspots["helper.py"]["risk"], \
        "of two files changing equally often, the complex one is riskier"


def test_change_coupling_sees_what_imports_cannot(report: dict) -> None:
    """No import connects core.py and helper.py, yet they always change together."""
    coupling = report["history"]["coupling"]
    pairs = [tuple(sorted(link["files"])) for link in coupling]
    assert ("core.py", "helper.py") in pairs
    link = next(c for c in coupling if sorted(c["files"]) == ["core.py", "helper.py"])
    assert link["degree"] >= 0.8

    edges = {(e["source"], e["target"]) for e in report["graph"]["edges"]}
    assert ("core", "helper") not in edges, "the static graph cannot see this link"


def test_untouched_file_ranks_last(report: dict) -> None:
    """Code nobody touches is not urgent, however complex it is."""
    ranking = [h["file"] for h in report["history"]["hotspots"]]
    assert ranking[0] == "core.py"
    assert ranking[-1] == "lonely.py"


def test_knowledge_island_detected(report: dict) -> None:
    islands = {item["file"] for item in report["history"]["knowledge_islands"]}
    assert "lonely.py" not in islands   # has not changed often enough
    assert all(item["main_author_share"] >= 0.9
               for item in report["history"]["knowledge_islands"])


def test_history_produces_findings(report: dict) -> None:
    rules = {f["rule"] for f in report["findings"]}
    assert "change_coupling" in rules


def test_rename_paths_are_normalised() -> None:
    assert history_mod._normalise_rename("src/{old => new}/a.py") == "src/new/a.py"
    assert history_mod._normalise_rename("old.py => new.py") == "new.py"
    assert history_mod._normalise_rename("plain.py") == "plain.py"


def test_analysis_works_without_git(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("def f():\n    return 1\n")
    result = analyze_source(str(tmp_path), history_commits=50)
    assert result["history"] == {}
    assert result["summary"]["modules"] == 1


# -------------------------------------------------------------------- SARIF #
@pytest.fixture(scope="module")
def demo_report() -> dict:
    demo = Path(__file__).resolve().parents[1] / "examples" / "demo_shop"
    return build_report(parse_repository(demo, sorted(demo.glob("*.py"))), Thresholds())


def test_sarif_shape(demo_report: dict) -> None:
    log = build_sarif(demo_report)
    assert log["version"] == "2.1.0" and log["$schema"].endswith("sarif-2.1.0.json")
    run = log["runs"][0]
    assert run["tool"]["driver"]["name"] == "ArchRay"
    assert run["results"] and run["tool"]["driver"]["rules"]


def test_sarif_results_are_well_formed(demo_report: dict) -> None:
    run = build_sarif(demo_report)["runs"][0]
    rule_ids = {rule["id"] for rule in run["tool"]["driver"]["rules"]}
    rules = run["tool"]["driver"]["rules"]

    for result in run["results"]:
        assert result["ruleId"] in rule_ids
        assert rules[result["ruleIndex"]]["id"] == result["ruleId"]
        assert result["level"] in ("error", "warning", "note", "none")
        assert result["message"]["text"]
        region = result["locations"][0]["physicalLocation"]["region"]
        assert region["startLine"] >= 1
        assert region.get("endLine", region["startLine"]) >= region["startLine"]
        assert result["partialFingerprints"]["archrayFindingV1"]


def test_sarif_severity_mapping(demo_report: dict) -> None:
    run = build_sarif(demo_report)["runs"][0]
    by_rule = {r["ruleId"]: r["level"] for r in run["results"]}
    assert by_rule["god_class"] == "error"
    assert by_rule["dip_concrete_dependency"] == "note"


def test_sarif_fingerprint_ignores_line_moves(demo_report: dict) -> None:
    from archray.sarif import _fingerprint
    finding = dict(demo_report["findings"][0])
    moved = {**finding, "line": finding["line"] + 120}
    assert _fingerprint(finding) == _fingerprint(moved)


def test_sarif_is_serialisable(demo_report: dict) -> None:
    assert json.loads(json.dumps(build_sarif(demo_report)))


# --------------------------------------------------------------- PR yorumu #
def test_pr_comment_without_baseline(demo_report: dict) -> None:
    text = render(demo_report)
    assert text.startswith("### ")
    assert "Most urgent technical debt" in text
    assert text.count("```") % 2 == 0


def test_pr_comment_leads_with_the_delta(demo_report: dict) -> None:
    with_diff = {**demo_report, "comparison": {
        "score_delta": -3.5, "new_count": 2, "fixed_count": 1,
        "verdict": "Net regression (-3.5 points): 2 opened, 1 resolved.",
        "new": [{"severity": "major", "title": "Uzun metot", "file": "a.py",
                 "line": 10, "symbol": "A.run"}],
        "fixed": [{"severity": "minor", "title": "Magic number", "file": "b.py",
                   "line": 2, "symbol": "B.calc"}]}}
    text = render(with_diff)
    assert "▼ -3.5 pts" in text
    assert "Net regression" in text and "✅ Resolved 1" in text
