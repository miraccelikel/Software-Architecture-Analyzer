"""Aggregation phase: turn raw findings into scores and a debt ranking."""

from __future__ import annotations

from .models import Finding, ModuleInfo, SEVERITY_ORDER

GRADES = ((90, "A"), (80, "B"), (70, "C"), (55, "D"), (0, "F"))
GRADE_LABEL = {
    "A": "Solid architecture — technical debt is under control.",
    "B": "Healthy — a few places need maintenance.",
    "C": "Fair — some areas should be cleaned up before the code grows.",
    "D": "Risky — the cost of change is rising fast.",
    "F": "Critical — the architecture needs restructuring.",
}


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def grade_for(score: float) -> str:
    for limit, letter in GRADES:
        if score >= limit:
            return letter
    return "F"


def compute(modules: list[ModuleInfo], findings: list[Finding],
            cycles: list[list[str]], thresholds) -> dict:
    sloc = sum(m.sloc for m in modules) or 1
    kloc = max(sloc / 1000.0, 0.25)

    functions = [f for m in modules for f in m.all_functions]
    complexities = [f.complexity for f in functions] or [1]
    avg_complexity = sum(complexities) / len(complexities)
    over_threshold = [c for c in complexities if c > thresholds.complexity_warning]
    over_ratio = len(over_threshold) / len(complexities)

    def weight_of(kind: str) -> float:
        return sum(f.weight for f in findings if f.kind == kind)

    def density(predicate) -> float:
        return sum(f.weight for f in findings if predicate(f)) / kloc

    smell_weight = weight_of("smell")
    solid_weight = weight_of("solid")

    severe_density = density(lambda f: f.severity in ("critical", "major"))
    minor_density = density(lambda f: f.severity == "minor")
    cycle_pressure = sum(len(c) for c in cycles) / max(len(modules), 1)

    # Saturating penalties: the first violations cost the most, and a large
    # project is not punished simply for having more code.
    severe_penalty = 38.0 * severe_density / (severe_density + 70.0)
    minor_penalty = 12.0 * minor_density / (minor_density + 35.0)
    complexity_penalty = min(16.0, over_ratio * 45.0 + max(0.0, avg_complexity - 4.0) * 3.0)
    cycle_penalty = min(14.0, len(cycles) * 6.0 / max(kloc ** 0.5, 1.0) + cycle_pressure * 8.0)

    complexity_score = _clamp(100 - over_ratio * 200 - max(0.0, avg_complexity - 4) * 6)
    smell_score = _clamp(100 - 100 * (smell_weight / kloc) / ((smell_weight / kloc) + 60))
    solid_score = _clamp(100 - 100 * (solid_weight / kloc) / ((solid_weight / kloc) + 45))
    graph_score = _clamp(100 - cycle_penalty * 5)

    overall = _clamp(100 - severe_penalty - minor_penalty - complexity_penalty - cycle_penalty)
    grade = grade_for(overall)

    return {
        "score": round(overall, 1),
        "grade": grade,
        "verdict": GRADE_LABEL[grade],
        "dimensions": [
            {"key": "complexity", "label": "Complexity", "score": round(complexity_score)},
            {"key": "smells", "label": "Code smells", "score": round(smell_score)},
            {"key": "solid", "label": "SOLID compliance", "score": round(solid_score)},
            {"key": "graph", "label": "Dependency structure", "score": round(graph_score)},
        ],
        "debt_density": round(severe_density + minor_density, 1),
        "avg_complexity": round(avg_complexity, 2),
        "max_complexity": max(complexities),
        "complex_function_ratio": round(over_ratio * 100, 1),
        "unstable_modules": sum(1 for m in modules if m.sloc > 40),
    }


def rank_debt(findings: list[Finding], limit: int = 5) -> list[dict]:
    """The findings worth fixing first: severity, then blast radius."""
    def impact(finding: Finding) -> tuple:
        metrics = finding.metrics
        radius = (metrics.get("complexity", 0) * 1.0
                  + metrics.get("loc", 0) * 0.06
                  + metrics.get("methods", 0) * 0.8
                  + metrics.get("size", 0) * 6
                  + metrics.get("lcom4", 0) * 4
                  + metrics.get("type_checks", 0) * 3
                  + metrics.get("branches", 0) * 2)
        return (SEVERITY_ORDER.get(finding.severity, 3), -(finding.weight + radius))

    ranked = sorted([f for f in findings if f.severity != "info"], key=impact)
    out = []
    for index, finding in enumerate(ranked[:limit], start=1):
        item = finding.to_dict()
        item["rank"] = index
        out.append(item)
    return out
