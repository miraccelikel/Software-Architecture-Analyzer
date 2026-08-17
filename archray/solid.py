"""SOLID checks built on top of the symbol table and the parsed AST metrics."""

from __future__ import annotations

from .config import Thresholds
from .graph import SymbolTable
from .models import ClassInfo, Finding, FunctionInfo, ModuleInfo

CONSTRUCTOR_LIKE = ("factory", "builder", "provider", "container", "module", "registry")
CREATION_METHODS = ("create", "make", "build", "new_", "from_", "of_", "get_instance")
COMPOSITION_ROOTS = ("main.py", "app.py", "wsgi.py", "asgi.py", "cli.py", "settings.py",
                     "container.py", "bootstrap.py", "conftest.py", "__main__.py")
VALUE_LIKE = ("dto", "config", "settings", "request", "response", "result", "event",
              "entity", "model", "record", "item", "node", "point", "vector")


class _UnionFind:
    def __init__(self, items: list[str]) -> None:
        self.parent = {item: item for item in items}

    def find(self, item: str) -> str:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra

    def groups(self) -> list[list[str]]:
        buckets: dict[str, list[str]] = {}
        for item in self.parent:
            buckets.setdefault(self.find(item), []).append(item)
        return [sorted(v) for v in buckets.values()]


def compute_lcom4(cls: ClassInfo) -> tuple[int, list[list[str]]]:
    """LCOM4: number of connected components in the method/field graph."""
    fields = set(cls.instance_attrs) | set(cls.class_attrs)
    # a constructor touches every field by definition, so leaving it in would
    # glue every component together and hide the lack of cohesion
    constructors = {"__init__", "__new__", "__post_init__", cls.name, f"~{cls.name}"}
    methods = [m for m in cls.methods
               if m.name not in constructors
               and m.name not in ("__repr__", "__str__", "__eq__", "__hash__")
               and not m.is_static]
    if len(methods) < 2:
        return 1, ([[m.name for m in methods]] if methods else [])

    names = [m.name for m in methods]
    union = _UnionFind(names)
    by_name = {m.name: m for m in methods}

    for i, left in enumerate(methods):
        left_fields = left.self_attrs & fields
        for right in methods[i + 1:]:
            right_fields = right.self_attrs & fields
            shares_field = bool(left_fields & right_fields)
            calls = right.name in left.self_calls or left.name in right.self_calls
            if shares_field or calls:
                union.union(left.name, right.name)

    # a method calling another method transitively glues the components
    for method in methods:
        for called in method.self_calls:
            if called in by_name:
                union.union(method.name, called)

    groups = union.groups()
    return len(groups), groups


def check_srp(cls: ClassInfo, thresholds: Thresholds) -> list[Finding]:
    components, groups = compute_lcom4(cls)
    cls.lcom4 = components
    fields = set(cls.instance_attrs) | set(cls.class_attrs)

    if components < thresholds.lcom4_warning or len(cls.methods) < 4 or len(fields) < 2:
        return []

    preview = " | ".join("{" + ", ".join(g[:4]) + "}" for g in groups[:3])
    severity = "major" if components >= 3 else "minor"
    return [Finding(
        kind="solid", rule="srp_low_cohesion", severity=severity,
        title="SRP violation — low cohesion (LCOM4)",
        message=(f"The methods of `{cls.name}` fall into {components} disconnected groups "
                 f"that never touch each other's fields: {preview}. That means the class is "
                 f"carrying {components} unrelated jobs — give each group its own class."),
        file=cls.file, line=cls.line, end_line=cls.end_line, symbol=cls.name,
        metrics={"lcom4": components, "groups": [g[:6] for g in groups[:5]],
                 "methods": cls.method_count, "fields": len(fields)},
    )]


def check_ocp(func: FunctionInfo, thresholds: Thresholds) -> list[Finding]:
    findings: list[Finding] = []
    longest = max((count for _line, count in func.branch_chains), default=0)
    label = f"{func.class_name}.{func.name}" if func.class_name else func.name

    if func.type_checks and len(func.type_checks) >= thresholds.ocp_type_checks:
        types = sorted({t for _line, t in func.type_checks})[:5]
        findings.append(Finding(
            kind="solid", rule="ocp_type_switch", severity="major",
            title="OCP violation — branching on type",
            message=(f"`{label}` performs {len(func.type_checks)} type checks "
                     f"({', '.join(types)}). Every new type forces this method to change too. "
                     f"Move the behaviour onto the types themselves (polymorphism) or use a "
                     f"Strategy."),
            file=func.file, line=func.type_checks[0][0], end_line=func.end_line,
            symbol=label, metrics={"type_checks": len(func.type_checks), "types": types},
        ))

    if longest >= thresholds.ocp_branches:
        line = next(line for line, count in func.branch_chains if count == longest)
        findings.append(Finding(
            kind="solid", rule="ocp_long_branch_chain", severity="minor",
            title="OCP violation — long branch chain",
            message=(f"`{label}` contains an if/elif (or match) chain with {longest} "
                     f"branches. Every new case means reopening this method. A lookup table "
                     f"or a Strategy makes it open for extension instead."),
            file=func.file, line=line, end_line=func.end_line, symbol=label,
            metrics={"branches": longest},
        ))
    return findings


def check_dip(module: ModuleInfo, cls: ClassInfo, symbols: SymbolTable) -> list[Finding]:
    findings: list[Finding] = []
    if any(key in cls.name.lower() for key in CONSTRUCTOR_LIKE):
        return findings
    if any(module.path.endswith(root) for root in COMPOSITION_ROOTS):
        return findings

    seen: set[str] = set()
    for method in cls.methods:
        if any(method.name.startswith(prefix) for prefix in CREATION_METHODS):
            continue
        for name, line in method.instantiations:
            simple = name.split(".")[-1]
            if simple in seen:
                continue
            target = symbols.lookup(simple, module.module)
            if target is None or target.qualname == cls.qualname:
                continue
            if target.is_abstract or target.is_exception or target.is_dataclass:
                continue
            if any(key in simple.lower() for key in VALUE_LIKE):
                continue

            abstraction = _abstraction_for(target, symbols)
            severity = "major" if abstraction else "minor"
            hint = (f"`{target.name}` already derives from `{abstraction}`; depend on "
                    f"`{abstraction}` instead."
                    if abstraction else
                    "Define an interface (ABC/Protocol) and inject the dependency through "
                    "the constructor.")
            seen.add(simple)
            findings.append(Finding(
                kind="solid", rule="dip_concrete_dependency", severity=severity,
                title="DIP violation — direct dependency on a concrete class",
                message=(f"`{cls.name}.{method.name}` constructs `{simple}()` directly. "
                         f"A high-level class is nailed to a low-level concrete one, so it "
                         f"cannot be tested with a substitute in its place. {hint}"),
                file=method.file, line=line, end_line=line,
                symbol=f"{cls.name}.{method.name}",
                metrics={"depends_on": target.qualname, "abstraction": abstraction},
            ))
    return findings


def _abstraction_for(cls: ClassInfo, symbols: SymbolTable) -> str:
    for base in cls.bases:
        parent = symbols.lookup(base, cls.module)
        if parent is not None and parent.is_abstract:
            return parent.name
    return ""


def check_isp(cls: ClassInfo, symbols: SymbolTable, thresholds: Thresholds) -> list[Finding]:
    abstract_methods = cls.abstract_methods
    if not cls.is_abstract or len(abstract_methods) <= thresholds.isp_abstract_methods:
        return []
    implementations = symbols.implementations_of(cls.name)
    names = [m.name for m in abstract_methods]
    return [Finding(
        kind="solid", rule="isp_fat_interface", severity="minor",
        title="ISP violation — fat interface",
        message=(f"`{cls.name}` forces {len(abstract_methods)} abstract methods on its "
                 f"implementers ({', '.join(names[:6])}…). The {len(implementations)} classes "
                 f"that implement it must write methods they do not need. Split the interface "
                 f"into smaller role-based ones."),
        file=cls.file, line=cls.line, end_line=cls.end_line, symbol=cls.name,
        metrics={"abstract_methods": len(abstract_methods),
                 "implementations": len(implementations), "names": names[:12]},
    )]


def check_lsp(cls: ClassInfo, symbols: SymbolTable) -> list[Finding]:
    findings: list[Finding] = []
    for base_name in cls.bases:
        base = symbols.lookup(base_name, cls.module)
        if base is None or base.qualname == cls.qualname:
            continue
        base_methods = {m.name: m for m in base.methods}
        for method in cls.methods:
            parent = base_methods.get(method.name)
            if parent is None:
                continue

            if method.raises_not_implemented and not parent.is_abstract and parent.loc >= 2:
                findings.append(Finding(
                    kind="solid", rule="lsp_refused_bequest", severity="major",
                    title="LSP violation — refused bequest",
                    message=(f"`{cls.name}.{method.name}` cancels working behaviour "
                             f"inherited from `{base.name}` by raising NotImplementedError. "
                             f"The subtype cannot stand in for its base. Prefer composition "
                             f"over inheritance here, or split the hierarchy."),
                    file=method.file, line=method.line, end_line=method.end_line,
                    symbol=f"{cls.name}.{method.name}",
                    metrics={"base": base.qualname},
                ))

            if len(method.params) < len(parent.params) and not method.is_property:
                findings.append(Finding(
                    kind="solid", rule="lsp_narrowed_signature", severity="minor",
                    title="LSP violation — narrowed signature",
                    message=(f"`{cls.name}.{method.name}` takes {len(method.params)} "
                             f"parameters while `{base.name}` declares the same method with "
                             f"{len(parent.params)}. A call written against the base type "
                             f"breaks on this subtype."),
                    file=method.file, line=method.line, end_line=method.end_line,
                    symbol=f"{cls.name}.{method.name}",
                    metrics={"params": len(method.params), "base_params": len(parent.params)},
                ))
    return findings


def run(modules: list[ModuleInfo], symbols: SymbolTable,
        thresholds: Thresholds) -> list[Finding]:
    findings: list[Finding] = []
    for module in modules:
        for func in module.functions:
            findings.extend(check_ocp(func, thresholds))
        for cls in module.classes:
            findings.extend(check_srp(cls, thresholds))
            findings.extend(check_isp(cls, symbols, thresholds))
            findings.extend(check_lsp(cls, symbols))
            findings.extend(check_dip(module, cls, symbols))
            for method in cls.methods:
                findings.extend(check_ocp(method, thresholds))
    return findings
