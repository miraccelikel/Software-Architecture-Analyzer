"""Compare two reports: what got worse, what got fixed.

A single score is a weak signal — nobody rewrites a codebase to move from C to B.
What a team can act on is the delta: three findings appeared in this branch, five
were resolved. Findings are matched on rule + file + symbol rather than on line
numbers, so shifting code up or down a file does not look like a change.
"""

from __future__ import annotations

from collections import Counter

TRACKED_KINDS = ("complexity", "smell", "solid", "graph")


def _key(finding: dict) -> tuple[str, str, str, str]:
    """Identity of a finding across runs — line numbers deliberately excluded.

    One symbol can carry several findings of the same rule (three concrete
    dependencies in one constructor), so the key also carries whatever names the
    other side of the relationship.
    """
    metrics = finding.get("metrics") or {}
    discriminator = str(metrics.get("depends_on") or metrics.get("base") or "")
    return (finding["rule"], finding["file"], finding.get("symbol", ""), discriminator)


def _index(findings: list[dict]) -> dict[tuple, list[dict]]:
    grouped: dict[tuple, list[dict]] = {}
    for finding in findings:
        if finding["severity"] != "info":
            grouped.setdefault(_key(finding), []).append(finding)
    return grouped


def compare(previous: dict, current: dict) -> dict:
    """Diff two ArchRay reports."""
    old = _index(previous.get("findings", []))
    new = _index(current.get("findings", []))

    appeared: list[dict] = []
    resolved: list[dict] = []
    for key in new.keys() | old.keys():
        before, after = old.get(key, []), new.get(key, [])
        if len(after) > len(before):
            appeared.extend(after[len(before):])
        elif len(before) > len(after):
            resolved.extend(before[len(after):])
    appeared.sort(key=lambda f: (f["severity"], f["file"], f["line"]))
    resolved.sort(key=lambda f: (f["severity"], f["file"]))

    old_total = sum(len(v) for v in old.values())
    old_health = previous.get("health", {})
    new_health = current.get("health", {})
    score_delta = round(new_health.get("score", 0) - old_health.get("score", 0), 1)

    return {
        "baseline": {
            "score": old_health.get("score"),
            "grade": old_health.get("grade"),
            "generated_at": previous.get("meta", {}).get("generated_at"),
            "repository": previous.get("repository", {}).get("name"),
            "findings": old_total,
        },
        "score_delta": score_delta,
        "grade_changed": old_health.get("grade") != new_health.get("grade"),
        "new_count": len(appeared),
        "fixed_count": len(resolved),
        "new_by_severity": dict(Counter(f["severity"] for f in appeared)),
        "fixed_by_severity": dict(Counter(f["severity"] for f in resolved)),
        "new": [_summarise(f) for f in appeared[:40]],
        "fixed": [_summarise(f) for f in resolved[:40]],
        "verdict": _verdict(score_delta, len(appeared), len(resolved)),
    }


def _summarise(finding: dict) -> dict:
    return {k: finding[k] for k in ("rule", "severity", "title", "file", "line", "symbol")}


def _verdict(score_delta: float, appeared: int, resolved: int) -> str:
    if appeared == 0 and resolved == 0:
        return "No architectural difference."
    if appeared == 0:
        return f"Improvement only: {resolved} findings resolved."
    if resolved == 0:
        return f"Regression only: {appeared} new findings."
    if score_delta > 0:
        return f"Net improvement (+{score_delta} points): {resolved} resolved, {appeared} opened."
    if score_delta < 0:
        return f"Net regression ({score_delta} points): {appeared} opened, {resolved} resolved."
    return f"Even: {appeared} opened, {resolved} resolved."
