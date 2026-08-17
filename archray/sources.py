"""Carry the source code itself into the report.

A finding that says "line 412 of core.py" is only useful to someone who has the
repository open. Embedding the code turns the report into something that can be
read on its own: a file tree, the source with its findings marked, and — when a
revision is given to compare against — a side-by-side diff.

Everything here is budgeted. A report is a document, not a copy of the
repository, so files are capped individually and in total, and the files that
carry findings are embedded first.
"""

from __future__ import annotations

from pathlib import Path

MAX_FILE_LINES = 1500
MAX_TOTAL_LINES = 26000
MAX_LINE_LENGTH = 400

ICON_BY_EXTENSION = {
    ".py": "py", ".java": "java", ".ts": "ts", ".tsx": "ts", ".cs": "cs",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
    ".h": "h", ".c": "c",
}


def _read(path: Path) -> list[str] | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return [line[:MAX_LINE_LENGTH] for line in text.splitlines()]


def collect(root: Path, modules: list, findings: list[dict]) -> dict:
    """Embed the source of the analysed files, richest in findings first."""
    by_file: dict[str, list[dict]] = {}
    for finding in findings:
        by_file.setdefault(finding["file"], []).append({
            "line": finding["line"],
            "end_line": finding.get("end_line") or finding["line"],
            "severity": finding["severity"],
            "rule": finding["rule"],
            "title": finding["title"],
            "symbol": finding.get("symbol", ""),
        })

    wanted: dict[str, str] = {}
    for module in modules:
        wanted[module.path] = module.language
        for extra in module.extra_sources:
            wanted[extra] = module.language

    # files with findings first, then the rest, smallest first so a budget
    # spent on one enormous generated file does not hide twenty readable ones
    ordered = sorted(
        wanted,
        key=lambda path: (0 if by_file.get(path) else 1, -len(by_file.get(path, [])), path),
    )

    files: dict[str, dict] = {}
    budget = MAX_TOTAL_LINES
    skipped = 0
    for relative in ordered:
        if budget <= 0:
            skipped += 1
            continue
        lines = _read(root / relative)
        if lines is None:
            skipped += 1
            continue
        truncated = len(lines) > MAX_FILE_LINES
        if truncated:
            lines = lines[:MAX_FILE_LINES]
        if len(lines) > budget:
            skipped += 1
            continue
        budget -= len(lines)
        files[relative] = {
            "language": wanted[relative],
            "lines": lines,
            "truncated": truncated,
            "findings": sorted(by_file.get(relative, []), key=lambda f: f["line"]),
        }

    return {"files": files, "tree": build_tree(files), "skipped": skipped}


def build_tree(files: dict[str, dict]) -> list[dict]:
    """A folder tree in the shape a Solution Explorer expects."""
    root: dict = {"name": "", "path": "", "type": "folder", "children": {}}

    for relative, payload in sorted(files.items()):
        parts = relative.split("/")
        node = root
        for depth, part in enumerate(parts[:-1]):
            path = "/".join(parts[: depth + 1])
            node = node["children"].setdefault(
                part, {"name": part, "path": path, "type": "folder", "children": {}})
        name = parts[-1]
        severities = {finding["severity"] for finding in payload["findings"]}
        node["children"][name] = {
            "name": name,
            "path": relative,
            "type": "file",
            "language": payload["language"],
            "icon": ICON_BY_EXTENSION.get("." + name.rsplit(".", 1)[-1], "file"),
            "lines": len(payload["lines"]),
            "findings": len(payload["findings"]),
            "worst": ("critical" if "critical" in severities
                      else "major" if "major" in severities
                      else "minor" if "minor" in severities
                      else ""),
        }

    def flatten(node: dict) -> list[dict]:
        out = []
        children = node["children"]
        for key in sorted(children, key=lambda k: (children[k]["type"] != "folder", k.lower())):
            child = children[key]
            if child["type"] == "folder":
                sub = flatten(child)
                out.append({
                    "name": child["name"], "path": child["path"], "type": "folder",
                    "children": sub,
                    "findings": sum(item.get("findings", 0) for item in sub),
                    "lines": sum(item.get("lines", 0) for item in sub),
                })
            else:
                out.append(child)
        return out

    return flatten(root)
