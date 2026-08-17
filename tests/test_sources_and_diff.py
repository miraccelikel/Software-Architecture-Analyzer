"""Embedded source, the file tree, and the line/word level code diff."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from archray import analyze_source
from archray.changes import compare as compare_structure
from archray.changes import materialise
from archray.codediff import align, to_unified
from archray.sources import build_tree

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "demo_shop"


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


# ------------------------------------------------------------ embedded source #
@pytest.fixture(scope="module")
def report() -> dict:
    return analyze_source(str(DEMO))


def test_source_is_embedded_in_the_report(report: dict) -> None:
    files = report["sources"]["files"]
    assert "legacy_order_service.py" in files
    entry = files["legacy_order_service.py"]
    assert entry["language"] == "python"
    assert entry["lines"][0].startswith('"""')
    assert len(entry["lines"]) > 400


def test_findings_are_attached_to_their_file(report: dict) -> None:
    entry = report["sources"]["files"]["legacy_order_service.py"]
    rules = {finding["rule"] for finding in entry["findings"]}
    assert "god_class" in rules
    assert all(1 <= f["line"] <= len(entry["lines"]) for f in entry["findings"])
    assert entry["findings"] == sorted(entry["findings"], key=lambda f: f["line"])


def test_every_embedded_file_appears_in_the_tree(report: dict) -> None:
    def walk(nodes):
        for node in nodes:
            if node["type"] == "folder":
                yield from walk(node["children"])
            else:
                yield node["path"]

    assert set(walk(report["sources"]["tree"])) == set(report["sources"]["files"])


def test_tree_nests_folders_and_totals_findings() -> None:
    files = {
        "src/core/engine.py": {"language": "python", "lines": ["x"],
                               "findings": [{"line": 1, "severity": "critical"}]},
        "src/util.py": {"language": "python", "lines": ["y"], "findings": []},
        "main.py": {"language": "python", "lines": ["z"], "findings": []},
    }
    tree = build_tree(files)
    folders = [node for node in tree if node["type"] == "folder"]
    assert [f["name"] for f in folders] == ["src"]
    assert folders[0]["findings"] == 1
    assert [node["name"] for node in tree if node["type"] == "file"] == ["main.py"]

    engine = folders[0]["children"][0]["children"][0]
    assert engine["path"] == "src/core/engine.py"
    assert engine["worst"] == "critical"
    assert engine["icon"] == "py"


# ------------------------------------------------------------------- diffing #
def test_alignment_pairs_lines() -> None:
    rows, stats = align(["a", "b", "c"], ["a", "B", "c", "d"])
    assert [row["type"] for row in rows] == ["equal", "replace", "equal", "insert"]
    assert stats == {"added": 2, "removed": 1}
    assert rows[3]["right"]["no"] == 4 and "left" not in rows[3]


def test_word_level_segments_mark_only_what_changed() -> None:
    rows, _ = align(["total = price * 2"], ["total = price * 3"])
    row = rows[0]
    assert row["type"] == "replace"
    changed_left = [text for flag, text in row["left"]["segments"] if flag]
    changed_right = [text for flag, text in row["right"]["segments"] if flag]
    assert changed_left == ["2"] and changed_right == ["3"]
    unchanged = "".join(text for flag, text in row["left"]["segments"] if not flag)
    assert unchanged == "total = price * "


def test_deleted_line_has_no_right_side() -> None:
    rows, _ = align(["keep", "drop"], ["keep"])
    assert rows[1]["type"] == "delete"
    assert "right" not in rows[1]


def test_unified_block_uses_diff_markers() -> None:
    rows, _ = align(["a", "b"], ["a", "c"])
    text = to_unified({"rows": rows})
    assert "-  b" in text.replace("- b", "-  b") or "- b" in text
    assert "+ c" in text


# ------------------------------------------------------- end to end on a repo #
@pytest.fixture(scope="module")
def diffed(tmp_path_factory) -> dict:
    root = tmp_path_factory.mktemp("diffed")
    (root / "calc.py").write_text(
        "def total(items):\n"
        "    result = 0\n"
        "    for item in items:\n"
        "        result += item\n"
        "    return result\n"
    )
    git(root, "init", "-q")
    git(root, "config", "user.email", "a@b.c")
    git(root, "config", "user.name", "Dev")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "baseline")

    (root / "calc.py").write_text(
        "def total(items, factor=2):\n"
        "    result = 0\n"
        "    for item in items:\n"
        "        if item > 9999:\n"
        "            continue\n"
        "        result += item * factor\n"
        "    return result\n"
    )
    snapshot = materialise(root, "HEAD")
    baseline = analyze_source(str(snapshot))
    current = analyze_source(str(root))
    return compare_structure(baseline, current, "HEAD", snapshot, root)


def test_file_diff_is_produced(diffed: dict) -> None:
    diffs = {diff["file"]: diff for diff in diffed["file_diffs"]}
    assert "calc.py" in diffs
    diff = diffs["calc.py"]
    assert diff["status"] == "modified"
    assert diff["stats"]["added"] >= 3
    assert diff["language"] == "python"


def test_function_diff_carries_the_real_lines(diffed: dict) -> None:
    diff = next(d for d in diffed["code"] if d["qualname"].endswith("total"))
    assert diff["kind"] == "modified"
    assert diff["complexity_after"] > diff["complexity_before"]
    texts = [row["right"]["text"] for row in diff["rows"] if "right" in row]
    assert any("factor" in text for text in texts)


def test_signature_change_is_marked_word_by_word(diffed: dict) -> None:
    diff = next(d for d in diffed["code"] if d["qualname"].endswith("total"))
    first = diff["rows"][0]
    assert first["type"] == "replace"
    assert "".join(t for f, t in first["right"]["segments"] if f).strip()
    assert "".join(t for f, t in first["left"]["segments"] if not f).startswith("def total(items")


def test_rows_keep_real_line_numbers(diffed: dict) -> None:
    diff = next(d for d in diffed["file_diffs"] if d["file"] == "calc.py")
    numbers = [row["right"]["no"] for row in diff["rows"] if "right" in row]
    assert numbers == list(range(1, len(numbers) + 1))


# ------------------------------------------------------ Visual Studio palette #
TEMPLATE = ROOT / "archray" / "ui" / "dashboard.html"


def editor_styles() -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    return text[text.index("IDE: solution explorer"):text.index("generic panels")]


@pytest.mark.parametrize("colour,meaning", [
    ("#1E1E1E", "editor background"),
    ("#252526", "tool window background"),
    ("#2B91AF", "line numbers"),
    ("#569CD6", "keywords"),
    ("#D8A0DF", "control flow keywords"),
    ("#D69D85", "strings"),
    ("#57A64A", "comments"),
    ("#4EC9B0", "types"),
    ("#B5CEA8", "numbers"),
    ("#4B1818", "removed lines"),
    ("#153D15", "added lines"),
])
def test_visual_studio_dark_palette(colour: str, meaning: str) -> None:
    assert colour in editor_styles(), f"missing the VS dark colour for {meaning}"


def test_editor_is_not_light_themed() -> None:
    """The panel must read as the dark IDE, not as a white page in a dark report."""
    styles = editor_styles()
    for light in ("--vs-bg:#FFFFFF", "background:#F6F6F6", "#EEEEF2", "#ADD6FF"):
        assert light not in styles, f"light theme leftover: {light}"


def test_print_stylesheet_still_inverts_for_paper() -> None:
    """Dark backgrounds waste ink, so printing flips the code panes to white."""
    styles = editor_styles()
    printed = styles[styles.index("@media print"):]
    assert "background:#fff!important" in printed
    assert "#FFDCE0!important" in printed and "#DFF7DF!important" in printed
