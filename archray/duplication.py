"""Copy-paste detection.

Every front-end stores a *structural fingerprint* for each function: the shape of
its body with identifiers and literal values erased. Two functions that were
copied and then renamed collide on that fingerprint, which is exactly the kind of
duplication a reviewer misses and a metric like "lines of code" never sees.
"""

from __future__ import annotations

from collections import defaultdict

from .config import Thresholds
from .models import Finding, FunctionInfo, ModuleInfo

STUB_NAMES = {"__init__", "__repr__", "__str__", "setUp", "toString", "equals",
              "hashCode", "Dispose", "ToString"}


def _label(func: FunctionInfo) -> str:
    return f"{func.class_name}.{func.name}" if func.class_name else func.name


def _is_candidate(func: FunctionInfo, thresholds: Thresholds) -> bool:
    """Trivial bodies are duplicated everywhere and mean nothing."""
    return (func.shape_size >= thresholds.clone_min_nodes
            and func.loc >= thresholds.clone_min_lines
            and not func.is_abstract
            and func.name not in STUB_NAMES)


def run(modules: list[ModuleInfo], thresholds: Thresholds) -> list[Finding]:
    groups: dict[str, list[FunctionInfo]] = defaultdict(list)
    for module in modules:
        for func in module.all_functions:
            if func.fingerprint and _is_candidate(func, thresholds):
                groups[func.fingerprint].append(func)

    findings: list[Finding] = []
    for clones in groups.values():
        if len(clones) < 2:
            continue
        clones.sort(key=lambda f: (f.file, f.line))
        anchor = max(clones, key=lambda f: f.loc)
        others = [f for f in clones if f is not anchor]
        spread_files = len({f.file for f in clones})

        severity = "major" if len(clones) >= 3 or anchor.loc >= 40 else "minor"
        where = "; ".join(f"{f.file}:{f.line} ({_label(f)})" for f in others[:4])
        if len(others) > 4:
            where += f" ve {len(others) - 4} tane daha"

        findings.append(Finding(
            kind="smell", rule="duplicate_code", severity=severity,
            title=f"Duplicate code ({len(clones)} copies)",
            message=(f"{len(others)} other functions are structurally identical to "
                     f"`{_label(anchor)}` — only names and literals differ: {where}. "
                     f"{'They are spread across files' if spread_files > 1 else 'They sit in one file'}, "
                     f"so every bug fix has to be applied to each copy by hand. "
                     f"Extract the shared behaviour."),
            file=anchor.file, line=anchor.line, end_line=anchor.end_line,
            symbol=_label(anchor),
            metrics={"copies": len(clones), "loc": anchor.loc, "files": spread_files,
                     "locations": [f"{f.file}:{f.line}" for f in clones[:8]]},
        ))
    return findings
