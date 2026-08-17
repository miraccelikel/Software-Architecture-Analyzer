"""Attach a small source excerpt to every finding.

The excerpt travels inside the report, so the dashboard can show the offending
lines without the repository — which is already deleted by then — being present.
"""

from __future__ import annotations

from .models import Finding, ModuleInfo

CONTEXT_BEFORE = 3
CONTEXT_AFTER = 6
MAX_LINES = 14
MAX_LINE_LENGTH = 200


def _dedent(lines: list[str]) -> tuple[list[str], int]:
    """Strip the common leading indentation so excerpts read well in a panel."""
    meaningful = [line for line in lines if line.strip()]
    if not meaningful:
        return lines, 0
    indent = min(len(line) - len(line.lstrip()) for line in meaningful)
    return [line[indent:] if line.strip() else "" for line in lines], indent


def excerpt_for(module: ModuleInfo, line: int, end_line: int = 0,
                source: list[str] | None = None) -> dict:
    """Lines around `line`, capped so a huge class does not ship its whole body."""
    source = module.source_lines if source is None else source
    if not source or line < 1:
        return {}

    start = max(line - CONTEXT_BEFORE, 1)
    span_end = max(end_line or line, line)
    stop = min(max(span_end, line + CONTEXT_AFTER), len(source))
    if stop - start + 1 > MAX_LINES:
        stop = start + MAX_LINES - 1
    stop = min(stop, len(source))

    raw = [text[:MAX_LINE_LENGTH] for text in source[start - 1:stop]]
    body, indent = _dedent(raw)
    return {
        "start": start,
        "focus": line,
        "lines": body,
        "indent": indent,
        "truncated": stop < span_end,
    }


def attach(findings: list[Finding], modules: list[ModuleInfo]) -> None:
    """A C++ module may span a header and an implementation file, so the lookup
    is by file path rather than by module."""
    sources: dict[str, tuple[ModuleInfo, list[str]]] = {}
    for module in modules:
        sources[module.path] = (module, module.source_lines)
        for path, lines in module.extra_sources.items():
            sources[path] = (module, lines)

    for finding in findings:
        entry = sources.get(finding.file)
        if entry is None:
            continue
        module, lines = entry
        finding.snippet = excerpt_for(module, finding.line, finding.end_line, lines)
