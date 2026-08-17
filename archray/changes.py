"""Structural diff between two versions of a codebase.

Reviewing generated code is hard for a specific reason: a text diff shows every
line that moved, which drowns the two or three facts that matter — a function
grew three times more complex, a new dependency appeared between two packages,
a class quietly lost a method.

This module compares two ArchRay reports at the level of *structure* rather than
text: functions and classes are matched by qualified name and compared by their
structural fingerprint, so a rename of a local variable is not a change while a
rewritten body is.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from . import bindings as bindings_mod
from . import codediff
from .compare import compare as compare_findings

COMPLEXITY_JUMP = 5          # below this a body change is not worth flagging
SEVERE_JUMP = 15


def materialise(repo_root: Path, revision: str) -> Path:
    """Extract a git revision into a temporary directory, read-only.

    `git archive` is used rather than `git worktree` or `git checkout` so that
    nothing about the working copy changes: analysing a revision must never
    disturb the code someone is editing.
    """
    target = Path(tempfile.mkdtemp(prefix="archray-rev-"))
    archive = subprocess.run(
        ["git", "-C", str(repo_root), "archive", "--format=tar", revision],
        capture_output=True,
    )
    if archive.returncode != 0:
        shutil.rmtree(target, ignore_errors=True)
        message = archive.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"Could not read revision '{revision}': {message}")

    extract = subprocess.run(["tar", "-x", "-C", str(target)], input=archive.stdout,
                             capture_output=True)
    if extract.returncode != 0:
        shutil.rmtree(target, ignore_errors=True)
        raise RuntimeError(f"Could not extract revision '{revision}'")
    return target


def _index(items: list[dict]) -> dict[str, dict]:
    return {item["qualname"]: item for item in items}


def compare(previous: dict, current: dict, revision: str = "",
            old_root: Path | None = None, new_root: Path | None = None) -> dict:
    """Diff two reports structurally, and — when both trees are still on disk —
    produce the code diffs a reviewer reads next."""
    old_functions = _index(previous.get("inventory", {}).get("functions", []))
    new_functions = _index(current.get("inventory", {}).get("functions", []))
    old_classes = _index(previous.get("inventory", {}).get("classes", []))
    new_classes = _index(current.get("inventory", {}).get("classes", []))

    added_functions = [new_functions[k] for k in new_functions.keys() - old_functions.keys()]
    removed_functions = [old_functions[k] for k in old_functions.keys() - new_functions.keys()]
    modified_functions = []
    for key in new_functions.keys() & old_functions.keys():
        before, after = old_functions[key], new_functions[key]
        if before["fingerprint"] == after["fingerprint"]:
            continue
        modified_functions.append({
            "qualname": key, "name": after["name"], "file": after["file"],
            "line": after["line"], "line_before": before["line"],
            "complexity_before": before["complexity"], "complexity_after": after["complexity"],
            "loc_before": before["loc"], "loc_after": after["loc"],
            "params_before": before["params"], "params_after": after["params"],
            "complexity_delta": after["complexity"] - before["complexity"],
        })

    added_classes = [new_classes[k] for k in new_classes.keys() - old_classes.keys()]
    removed_classes = [old_classes[k] for k in old_classes.keys() - new_classes.keys()]
    modified_classes = []
    for key in new_classes.keys() & old_classes.keys():
        before, after = old_classes[key], new_classes[key]
        if before["methods"] == after["methods"] and before["bases"] == after["bases"]:
            continue
        modified_classes.append({
            "qualname": key, "name": after["name"], "file": after["file"],
            "line": after["line"],
            "methods_before": before["methods"], "methods_after": after["methods"],
            "bases_before": before["bases"], "bases_after": after["bases"],
        })

    old_edges = {(e["source"], e["target"]) for e in previous.get("graph", {}).get("edges", [])}
    new_edges = {(e["source"], e["target"]) for e in current.get("graph", {}).get("edges", [])}

    for group in (added_functions, removed_functions, added_classes, removed_classes):
        group.sort(key=lambda item: (item["file"], item.get("line", 0)))
    modified_functions.sort(key=lambda item: -abs(item["complexity_delta"]))
    modified_classes.sort(key=lambda item: item["file"])

    result = {
        "revision": revision,
        "baseline_score": previous.get("health", {}).get("score"),
        "score": current.get("health", {}).get("score"),
        "score_delta": round(current.get("health", {}).get("score", 0)
                             - previous.get("health", {}).get("score", 0), 1),
        "functions": {
            "added": added_functions[:60], "removed": removed_functions[:60],
            "modified": modified_functions[:60],
            "counts": {"added": len(added_functions), "removed": len(removed_functions),
                       "modified": len(modified_functions)},
        },
        "classes": {
            "added": added_classes[:40], "removed": removed_classes[:40],
            "modified": modified_classes[:40],
            "counts": {"added": len(added_classes), "removed": len(removed_classes),
                       "modified": len(modified_classes)},
        },
        "edges": {
            "added": [{"source": s, "target": t} for s, t in sorted(new_edges - old_edges)][:40],
            "removed": [{"source": s, "target": t} for s, t in sorted(old_edges - new_edges)][:40],
        },
        "findings": compare_findings(previous, current),
    }
    if old_root is not None and new_root is not None:
        result["code"] = codediff.for_functions(result, old_root, new_root)
        result["file_diffs"] = _file_diffs(previous, current, old_root, new_root)
    else:
        result["code"] = []
        result["file_diffs"] = []

    result["bindings"] = bindings_mod.compare(previous, current)
    result["highlights"] = _highlights(result)
    result["headline"] = _headline(result)
    return result


MAX_FILE_DIFFS = 25
MAX_FILE_DIFF_LINES = 900


def _file_diffs(previous: dict, current: dict, old_root: Path, new_root: Path) -> list[dict]:
    """Whole-file diffs, so the viewer can show a file the way an IDE would."""
    def paths(report: dict) -> dict[str, str]:
        return {module["file"]: module.get("language", "")
                for module in report.get("inventory", {}).get("modules", [])}

    old_paths, new_paths = paths(previous), paths(current)
    diffs: list[dict] = []
    for relative in sorted(set(old_paths) | set(new_paths)):
        old_lines = codediff.read_range(old_root, relative, 1, 10_000_000)
        new_lines = codediff.read_range(new_root, relative, 1, 10_000_000)
        if old_lines == new_lines:
            continue
        if max(len(old_lines), len(new_lines)) > MAX_FILE_DIFF_LINES:
            continue
        rows, stats = codediff.align(old_lines, new_lines)
        status = ("added" if not old_lines else "removed" if not new_lines else "modified")
        diffs.append({
            "file": relative,
            "language": new_paths.get(relative) or old_paths.get(relative, ""),
            "status": status,
            "stats": stats,
            "rows": rows,
        })
        if len(diffs) >= MAX_FILE_DIFFS:
            break
    return diffs


def _highlights(result: dict) -> list[dict]:
    """The handful of facts a reviewer should not miss."""
    notes: list[dict] = []

    for change in result["functions"]["modified"]:
        delta = change["complexity_delta"]
        if delta >= COMPLEXITY_JUMP:
            notes.append({
                "level": "warning" if delta >= SEVERE_JUMP else "info",
                "kind": "complexity_growth",
                "text": (f"`{change['qualname']}` grew from complexity "
                         f"{change['complexity_before']} to {change['complexity_after']} "
                         f"(+{delta})"),
                "file": change["file"], "line": change["line"],
            })

    for edge in result["edges"]["added"]:
        notes.append({
            "level": "info", "kind": "new_dependency",
            "text": f"New dependency: `{edge['source']}` → `{edge['target']}`",
            "file": "", "line": 0,
        })

    for removed in result["functions"]["removed"][:10]:
        notes.append({
            "level": "warning", "kind": "removed_code",
            "text": f"`{removed['qualname']}` was removed",
            "file": removed["file"], "line": 0,
        })

    for broken in result.get("bindings", {}).get("broken", [])[:5]:
        notes.insert(0, {
            "level": "warning", "kind": "broken_binding",
            "text": (f"Cross-language contract broken: `{broken['symbol']}` — "
                     + (broken["problems"][0] if broken["problems"]
                        else "the native symbol is gone")),
            "file": broken["managed"]["file"], "line": broken["managed"]["line"],
        })

    for finding in result["findings"]["new"][:10]:
        if finding["severity"] in ("critical", "major"):
            notes.append({
                "level": "warning", "kind": "new_finding",
                "text": f"New {finding['severity']} finding: {finding['title']} "
                        f"({finding['symbol'] or finding['file']})",
                "file": finding["file"], "line": finding["line"],
            })

    order = {"warning": 0, "info": 1}
    notes.sort(key=lambda note: order.get(note["level"], 2))
    return notes[:20]


def _headline(result: dict) -> str:
    functions = result["functions"]["counts"]
    classes = result["classes"]["counts"]
    parts = []
    if functions["added"]:
        parts.append(f"{functions['added']} new functions")
    if functions["modified"]:
        parts.append(f"{functions['modified']} rewritten")
    if functions["removed"]:
        parts.append(f"{functions['removed']} removed")
    if classes["added"]:
        parts.append(f"{classes['added']} new classes")
    if result["edges"]["added"]:
        parts.append(f"{len(result['edges']['added'])} new dependencies")
    if not parts:
        return "No structural change."
    delta = result["score_delta"]
    trend = ("architecture score unchanged" if delta == 0
             else f"score {'+' if delta > 0 else ''}{delta}")
    return ", ".join(parts) + f" — {trend}."
