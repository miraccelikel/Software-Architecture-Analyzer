"""Inline suppression: `# archray: ignore` next to the offending line.

A static analyser without an escape hatch gets switched off entirely. Two forms
are supported, on the finding's line or the line above it:

    total = price * 1.18          # archray: ignore[magic_number]
    def legacy_handler(...):      # archray: ignore
"""

from __future__ import annotations

import re

from .models import Finding, ModuleInfo

MARKER = re.compile(r"archray:\s*ignore(?:\[([\w,\s]+)\])?", re.IGNORECASE)


def _suppressed_rules(line: str) -> set[str] | None:
    """None if the line has no marker, otherwise the rules it silences.

    An empty set means "silence everything on this line".
    """
    match = MARKER.search(line)
    if match is None:
        return None
    listed = match.group(1)
    return {r.strip() for r in listed.split(",") if r.strip()} if listed else set()


def apply(findings: list[Finding], modules: list[ModuleInfo],
          ignored_rules: list[str] | None = None) -> tuple[list[Finding], int]:
    """Return the surviving findings and how many were silenced."""
    globally_ignored = set(ignored_rules or [])
    sources: dict[str, list[str]] = {}
    for module in modules:
        sources[module.path] = module.source_lines
        sources.update(module.extra_sources)

    kept: list[Finding] = []
    for finding in findings:
        if finding.rule in globally_ignored:
            continue

        lines = sources.get(finding.file, [])
        silenced = False
        for offset in (0, -1):
            index = finding.line - 1 + offset
            if 0 <= index < len(lines):
                rules = _suppressed_rules(lines[index])
                if rules is not None and (not rules or finding.rule in rules):
                    silenced = True
                    break
        if not silenced:
            kept.append(finding)
    return kept, len(findings) - len(kept)
