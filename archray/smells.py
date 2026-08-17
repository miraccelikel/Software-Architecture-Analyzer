"""Rule engine — cyclomatic complexity thresholds and classic code smells."""

from __future__ import annotations

from .config import Thresholds
from .models import ClassInfo, Finding, FunctionInfo, ModuleInfo

DUNDER_EXEMPT = {"__init__", "__new__", "__repr__", "__str__", "__eq__", "__hash__"}


def _label(func: FunctionInfo) -> str:
    return f"{func.class_name}.{func.name}" if func.class_name else func.name


def check_complexity(func: FunctionInfo, thresholds: Thresholds) -> list[Finding]:
    findings: list[Finding] = []
    if func.complexity > thresholds.complexity_critical:
        severity = "critical"
    elif func.complexity > thresholds.complexity_warning:
        severity = "major"
    else:
        severity = ""

    if severity:
        findings.append(Finding(
            kind="complexity",
            rule="high_cyclomatic_complexity",
            severity=severity,
            title="High cyclomatic complexity",
            message=(f"`{_label(func)}` has a cyclomatic complexity of {func.complexity} "
                     f"(threshold {thresholds.complexity_warning}). That is roughly "
                     f"{func.complexity} independent execution paths, so full branch "
                     f"coverage needs as many tests. Split it into smaller functions."),
            file=func.file, line=func.line, end_line=func.end_line,
            symbol=_label(func),
            metrics={"complexity": func.complexity, "loc": func.loc},
        ))

    if func.max_nesting > thresholds.max_nesting:
        findings.append(Finding(
            kind="smell",
            rule="deep_nesting",
            severity="minor",
            title="Deep nesting",
            message=(f"`{_label(func)}` nests blocks {func.max_nesting} levels deep. "
                     f"Guard clauses and early returns usually flatten this."),
            file=func.file, line=func.line, end_line=func.end_line,
            symbol=_label(func), metrics={"max_nesting": func.max_nesting},
        ))
    return findings


def check_function_smells(func: FunctionInfo, thresholds: Thresholds) -> list[Finding]:
    findings: list[Finding] = []

    if func.loc > thresholds.long_method_loc:
        severity = "major" if func.loc > thresholds.very_long_method_loc else "minor"
        findings.append(Finding(
            kind="smell", rule="long_method", severity=severity,
            title="Long method",
            message=(f"`{_label(func)}` is {func.loc} lines long (threshold "
                     f"{thresholds.long_method_loc}). A method should fit on one screen so "
                     f"a reader can hold all of it in their head at once."),
            file=func.file, line=func.line, end_line=func.end_line,
            symbol=_label(func), metrics={"loc": func.loc},
        ))

    if len(func.params) > thresholds.max_parameters:
        findings.append(Finding(
            kind="smell", rule="too_many_parameters", severity="minor",
            title="Too many parameters",
            message=(f"`{_label(func)}` takes {len(func.params)} parameters: "
                     f"{', '.join(func.params[:8])}. Parameters that always travel together "
                     f"belong in a parameter object."),
            file=func.file, line=func.line, end_line=func.end_line,
            symbol=_label(func), metrics={"params": len(func.params)},
        ))

    if len(func.magic_numbers) >= thresholds.magic_number_min:
        values = sorted({str(v) for _line, v in func.magic_numbers})
        first_line = min(line for line, _v in func.magic_numbers)
        findings.append(Finding(
            kind="smell", rule="magic_number", severity="minor",
            title="Magic number",
            message=(f"Conditions in `{_label(func)}` compare against unnamed constants: "
                     f"{', '.join(values[:6])}. Give them names or an enum: "
                     f"`if status == Status.FAILED` rather than `if status == 4`."),
            file=func.file, line=first_line, end_line=first_line,
            symbol=_label(func),
            metrics={"values": values, "occurrences": len(func.magic_numbers)},
        ))
    return findings


def check_class_smells(cls: ClassInfo, thresholds: Thresholds) -> list[Finding]:
    findings: list[Finding] = []
    total_complexity = sum(m.complexity for m in cls.methods)

    if cls.loc > thresholds.god_class_loc and cls.method_count > thresholds.god_class_methods:
        findings.append(Finding(
            kind="smell", rule="god_class", severity="critical",
            title="God class",
            message=(f"`{cls.name}` spans {cls.loc} lines across {cls.method_count} methods "
                     f"(thresholds {thresholds.god_class_loc} lines / "
                     f"{thresholds.god_class_methods} methods). A class this size has almost "
                     f"certainly absorbed several responsibilities; split it along them."),
            file=cls.file, line=cls.line, end_line=cls.end_line, symbol=cls.name,
            metrics={"loc": cls.loc, "methods": cls.method_count,
                     "complexity": total_complexity, "attributes": len(cls.instance_attrs)},
        ))
    elif cls.loc > thresholds.large_class_loc or cls.method_count > thresholds.large_class_methods:
        findings.append(Finding(
            kind="smell", rule="large_class", severity="minor",
            title="Large class",
            message=(f"`{cls.name}` is {cls.loc} lines / {cls.method_count} methods. "
                     f"Not a god class yet, but worth watching which way it grows."),
            file=cls.file, line=cls.line, end_line=cls.end_line, symbol=cls.name,
            metrics={"loc": cls.loc, "methods": cls.method_count},
        ))

    if len(cls.instance_attrs) > 15 and not cls.is_dataclass:
        findings.append(Finding(
            kind="smell", rule="too_many_fields", severity="minor",
            title="Too many fields",
            message=(f"`{cls.name}` holds {len(cls.instance_attrs)} instance fields. "
                     f"Fields that are always used together can move into a value object."),
            file=cls.file, line=cls.line, end_line=cls.end_line, symbol=cls.name,
            metrics={"attributes": len(cls.instance_attrs)},
        ))
    return findings


def check_dead_private_methods(cls: ClassInfo) -> list[Finding]:
    """A private method nobody calls cannot be called from anywhere else either."""
    called: set[str] = set()
    for method in cls.methods:
        called |= method.self_calls
    called |= set(cls.class_attrs)      # may be assigned as a method reference

    findings: list[Finding] = []
    for method in cls.methods:
        name = method.name
        # a private constructor is a deliberate design choice (Singleton, static
        # utility class), not dead code — and nothing "calls" it by name
        if name in (cls.name, f"~{cls.name}", "__init__", "__new__"):
            continue
        is_private = (name.startswith("_") and not name.startswith("__")) \
            or "private" in method.decorators
        if not is_private or method.is_abstract or name in called:
            continue
        if any(keyword in " ".join(method.decorators).lower()
               for keyword in ("property", "override", "test", "setter")):
            continue
        findings.append(Finding(
            kind="smell", rule="dead_private_method", severity="minor",
            title="Unused private method",
            message=(f"`{cls.name}.{name}` is private but no method of the class calls it. "
                     f"Either it is dead code and should go, or it is behaviour that was "
                     f"accidentally made unreachable. (Dynamic dispatch or subclass use can "
                     f"make this a false positive.)"),
            file=method.file, line=method.line, end_line=method.end_line,
            symbol=f"{cls.name}.{name}", metrics={"loc": method.loc},
        ))
    return findings


def run(modules: list[ModuleInfo], thresholds: Thresholds) -> list[Finding]:
    findings: list[Finding] = []
    for module in modules:
        if module.parse_error:
            findings.append(Finding(
                kind="smell", rule="parse_error", severity="info",
                title="File could not be parsed",
                message=f"Skipped because of a syntax error: {module.parse_error}",
                file=module.path, line=1, symbol=module.module,
            ))
            continue
        for func in module.all_functions:
            findings.extend(check_complexity(func, thresholds))
            findings.extend(check_function_smells(func, thresholds))
        for cls in module.classes:
            findings.extend(check_class_smells(cls, thresholds))
            findings.extend(check_dead_private_methods(cls))
    return findings
