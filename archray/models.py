"""Core data structures shared by every analysis stage."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2, "info": 3}
SEVERITY_WEIGHT = {"critical": 12.0, "major": 5.0, "minor": 1.5, "info": 0.0}


@dataclass
class Finding:
    """A single rule violation located in the source tree."""

    kind: str  # complexity | smell | solid | graph
    rule: str  # god_class, srp_lcom, dip_concrete_dependency ...
    severity: str  # critical | major | minor | info
    title: str
    message: str
    file: str
    line: int
    end_line: int = 0
    symbol: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    snippet: dict[str, Any] = field(default_factory=dict)

    @property
    def weight(self) -> float:
        return SEVERITY_WEIGHT.get(self.severity, 1.0)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["end_line"] = self.end_line or self.line
        return d


@dataclass
class FunctionInfo:
    name: str
    qualname: str
    file: str
    line: int
    end_line: int
    loc: int
    params: list[str]
    param_types: list[str] = field(default_factory=list)
    complexity: int = 1
    max_nesting: int = 0
    is_method: bool = False
    class_name: str = ""
    decorators: list[str] = field(default_factory=list)
    is_abstract: bool = False
    is_static: bool = False
    is_classmethod: bool = False
    is_property: bool = False
    returns_self: bool = False
    raises_not_implemented: bool = False
    self_attrs: set[str] = field(default_factory=set)
    self_calls: set[str] = field(default_factory=set)
    instantiations: list[tuple[str, int]] = field(default_factory=list)
    branch_chains: list[tuple[int, int]] = field(default_factory=list)  # (line, elif count)
    type_checks: list[tuple[int, str]] = field(default_factory=list)
    magic_numbers: list[tuple[int, Any]] = field(default_factory=list)
    returns_types: set[str] = field(default_factory=set)
    annotations: dict[str, str] = field(default_factory=dict)
    fingerprint: str = ""       # structural signature, stripped of names and literals
    shape_size: int = 0         # how many nodes went into that signature

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "qualname": self.qualname,
            "file": self.file,
            "line": self.line,
            "loc": self.loc,
            "params": self.params,
            "complexity": self.complexity,
            "max_nesting": self.max_nesting,
            "class_name": self.class_name,
        }


@dataclass
class ClassInfo:
    name: str
    qualname: str
    file: str
    module: str
    line: int
    end_line: int
    loc: int
    bases: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    methods: list[FunctionInfo] = field(default_factory=list)
    class_attrs: dict[str, str] = field(default_factory=dict)
    instance_attrs: set[str] = field(default_factory=set)
    is_abstract: bool = False
    is_exception: bool = False
    is_dataclass: bool = False
    lcom4: int = 1

    @property
    def method_count(self) -> int:
        return len(self.methods)

    @property
    def abstract_methods(self) -> list[FunctionInfo]:
        return [m for m in self.methods if m.is_abstract]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "qualname": self.qualname,
            "file": self.file,
            "module": self.module,
            "line": self.line,
            "loc": self.loc,
            "bases": self.bases,
            "methods": self.method_count,
            "is_abstract": self.is_abstract,
            "lcom4": self.lcom4,
            "complexity": sum(m.complexity for m in self.methods),
        }


@dataclass
class ModuleInfo:
    path: str  # repo-relative path
    module: str  # dotted module name
    loc: int
    sloc: int
    language: str = ""
    imports: list[dict[str, Any]] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    parse_error: str = ""
    source_lines: list[str] = field(default_factory=list, repr=False)
    extra_sources: dict[str, list[str]] = field(default_factory=dict, repr=False)

    @property
    def all_functions(self) -> list[FunctionInfo]:
        out = list(self.functions)
        for c in self.classes:
            out.extend(c.methods)
        return out
