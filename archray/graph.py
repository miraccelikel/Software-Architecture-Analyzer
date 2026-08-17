"""Indexing & resolving phase: symbol table + module dependency graph."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from .models import ClassInfo, Finding, ModuleInfo


class SymbolTable:
    """Index of every class defined in the project plus import resolution."""

    def __init__(self, modules: list[ModuleInfo]) -> None:
        self.modules: dict[str, ModuleInfo] = {m.module: m for m in modules}
        self.classes_by_qualname: dict[str, ClassInfo] = {}
        self.classes_by_name: dict[str, list[ClassInfo]] = defaultdict(list)
        self.module_of_class: dict[str, str] = {}
        # class name -> direct subclasses
        self.subclasses: dict[str, list[ClassInfo]] = defaultdict(list)

        for module in modules:
            for cls in module.classes:
                self.classes_by_qualname[cls.qualname] = cls
                self.classes_by_name[cls.name].append(cls)
                self.module_of_class[cls.name] = module.module

        for cls in self.classes_by_qualname.values():
            for base in cls.bases:
                simple = base.split("[")[0].split(".")[-1].strip()
                if simple in self.classes_by_name:
                    self.subclasses[simple].append(cls)

    # ------------------------------------------------------------------ #
    def is_project_class(self, name: str) -> bool:
        return name.split(".")[-1].split("[")[0] in self.classes_by_name

    def lookup(self, name: str, from_module: str = "") -> ClassInfo | None:
        """Resolve a simple or dotted class name to a project class."""
        simple = name.split(".")[-1].split("[")[0].strip()
        candidates = self.classes_by_name.get(simple)
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        for cls in candidates:  # prefer a class defined in the calling module
            if cls.module == from_module:
                return cls
        module = self.modules.get(from_module)
        if module:
            imported = {imp["module"] for imp in module.imports}
            for cls in candidates:
                if cls.module in imported:
                    return cls
        return candidates[0]

    def implementations_of(self, base_name: str) -> list[ClassInfo]:
        return self.subclasses.get(base_name, [])

    def resolve_import(self, module: ModuleInfo, imp: dict) -> list[str]:
        """Map an import statement onto project module names."""
        level = imp.get("level", 0)
        target = imp.get("module") or ""
        if level:
            parts = module.module.split(".")
            base = parts[: max(len(parts) - level, 0)]
            target = ".".join([*base, target]) if target else ".".join(base)

        if not target:
            # `from . import graph` at the root of the analysed package
            return [name for name in imp.get("names", []) if name in self.modules]

        resolved: list[str] = []
        if target in self.modules:
            resolved.append(target)
        for name in imp.get("names", []):
            candidate = f"{target}.{name}" if target else name
            if candidate in self.modules:
                resolved.append(candidate)
        if not resolved:
            # `import package.module` where only a prefix matches a package
            for known in self.modules:
                if known == target or known.startswith(target + "."):
                    resolved.append(known)
                    break
        return resolved


@dataclass
class DependencyGraph:
    nodes: dict[str, dict] = field(default_factory=dict)
    edges: dict[tuple[str, str], int] = field(default_factory=dict)
    cycles: list[list[str]] = field(default_factory=list)
    edge_kinds: dict[tuple[str, str], str] = field(default_factory=dict)

    def add_edge(self, source: str, target: str, weight: int = 1) -> None:
        if source == target:
            return
        key = (source, target)
        self.edges[key] = self.edges.get(key, 0) + weight

    def adjacency(self) -> dict[str, list[str]]:
        adj: dict[str, list[str]] = {node: [] for node in self.nodes}
        for (src, dst) in self.edges:
            adj.setdefault(src, []).append(dst)
        return adj


def build_graph(modules: list[ModuleInfo], symbols: SymbolTable) -> DependencyGraph:
    graph = DependencyGraph()

    for module in modules:
        complexity = [f.complexity for f in module.all_functions]
        graph.nodes[module.module] = {
            "id": module.module,
            "label": module.module.split(".")[-1],
            "file": module.path,
            "loc": module.loc,
            "classes": len(module.classes),
            "functions": len(module.all_functions),
            "max_complexity": max(complexity, default=0),
            "avg_complexity": round(sum(complexity) / len(complexity), 2) if complexity else 0,
            "fan_in": 0,
            "fan_out": 0,
            "dependents": 0,
            "dependencies": 0,
            "instability": 0.0,
            "in_cycle": False,
            "findings": 0,
            "score_penalty": 0.0,
        }

    for module in modules:
        for imp in module.imports:
            for target in symbols.resolve_import(module, imp):
                weight = max(len(imp.get("names", [])), 1)
                graph.add_edge(module.module, target, weight)


    # inheritance, field types and object creation couple modules as surely as
    # an import statement does — and in Java they often replace it entirely
    for source, target, _kind, weight in class_relations(modules, symbols):
        if source.module != target.module:
            graph.add_edge(source.module, target.module, weight)

    for (src, dst), weight in graph.edges.items():
        # fan_in/out weigh how *often* something is used; dependents/dependencies
        # count how *many* modules are involved, which is what a reader wants
        if src in graph.nodes:
            graph.nodes[src]["fan_out"] += weight
            graph.nodes[src]["dependencies"] += 1
        if dst in graph.nodes:
            graph.nodes[dst]["fan_in"] += weight
            graph.nodes[dst]["dependents"] += 1

    for node in graph.nodes.values():
        total = node["fan_in"] + node["fan_out"]
        node["instability"] = round(node["fan_out"] / total, 2) if total else 0.0

    graph.cycles = find_cycles(graph)
    for cycle in graph.cycles:
        for module_name in cycle:
            if module_name in graph.nodes:
                graph.nodes[module_name]["in_cycle"] = True
    return graph


def find_cycles(graph: DependencyGraph) -> list[list[str]]:
    """Tarjan's strongly connected components (iterative, size > 1)."""
    adjacency = graph.adjacency()
    index_counter = [0]
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    components: list[list[str]] = []

    for root in adjacency:
        if root in indices:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            node, child_index = work[-1]
            if child_index == 0:
                indices[node] = lowlink[node] = index_counter[0]
                index_counter[0] += 1
                stack.append(node)
                on_stack.add(node)

            recursed = False
            neighbours = adjacency.get(node, [])
            for offset in range(child_index, len(neighbours)):
                neighbour = neighbours[offset]
                work[-1] = (node, offset + 1)
                if neighbour not in indices:
                    work.append((neighbour, 0))
                    recursed = True
                    break
                if neighbour in on_stack:
                    lowlink[node] = min(lowlink[node], indices[neighbour])
            if recursed:
                continue

            if lowlink[node] == indices[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                if len(component) > 1:
                    components.append(sorted(component))
            work.pop()
            if work:
                parent = work[-1][0]
                lowlink[parent] = min(lowlink[parent], lowlink[node])

    return components


def class_relations(modules: list[ModuleInfo], symbols: SymbolTable):
    """Yield (source class, target class, relationship, weight) for the project.

    Import statements alone are not enough: in Java two classes of the same
    package need no import, and a field declaration is the strongest coupling
    signal there is.
    """
    for module in modules:
        for cls in module.classes:
            candidates: list[tuple[str, str, int]] = []
            for base in cls.bases:
                candidates.append((base, "extends", 3))
            for declared in cls.class_attrs.values():
                for name in _annotation_names(declared):
                    candidates.append((name, "uses", 2))
            for method in cls.methods:
                for created, _line in method.instantiations:
                    candidates.append((created, "creates", 2))
                for annotation in method.annotations.values():
                    for name in _annotation_names(annotation):
                        candidates.append((name, "uses", 1))

            for raw_name, kind, weight in candidates:
                target = symbols.lookup(raw_name, cls.module)
                if target is not None and target.qualname != cls.qualname:
                    yield cls, target, kind, weight


def build_class_graph(modules: list[ModuleInfo], symbols: SymbolTable) -> DependencyGraph:
    """Class-level view: who inherits from, creates, or takes in whom."""
    graph = DependencyGraph()

    for module in modules:
        for cls in module.classes:
            graph.nodes[cls.qualname] = {
                "id": cls.qualname,
                "label": cls.name,
                "file": cls.file,
                "module": cls.module,
                "line": cls.line,
                "loc": cls.loc,
                "classes": len(cls.bases),
                "functions": cls.method_count,
                "max_complexity": max((m.complexity for m in cls.methods), default=0),
                "avg_complexity": round(
                    sum(m.complexity for m in cls.methods) / cls.method_count, 2
                ) if cls.method_count else 0,
                "is_abstract": cls.is_abstract,
                "lcom4": cls.lcom4,
                "fan_in": 0, "fan_out": 0, "dependents": 0, "dependencies": 0,
                "instability": 0.0, "in_cycle": False, "findings": 0,
                "score_penalty": 0.0,
            }

    kinds: dict[tuple[str, str], str] = {}
    for source, target, kind, weight in class_relations(modules, symbols):
        graph.add_edge(source.qualname, target.qualname, weight)
        key = (source.qualname, target.qualname)
        if kinds.get(key) != "extends":
            kinds[key] = kind

    for (src, dst), weight in graph.edges.items():
        graph.nodes[src]["fan_out"] += weight
        graph.nodes[src]["dependencies"] += 1
        graph.nodes[dst]["fan_in"] += weight
        graph.nodes[dst]["dependents"] += 1
    for node in graph.nodes.values():
        total = node["fan_in"] + node["fan_out"]
        node["instability"] = round(node["fan_out"] / total, 2) if total else 0.0

    graph.cycles = find_cycles(graph)
    for cycle in graph.cycles:
        for member in cycle:
            graph.nodes[member]["in_cycle"] = True

    graph.edge_kinds = kinds
    return graph


def _annotation_names(annotation: str) -> list[str]:
    """Pull class names out of an annotation such as `list[Order] | None`."""
    parts = re.split(r"[\[\]\|,\s]+", annotation or "")
    return [p.split(".")[-1] for p in parts
            if p and p.split(".")[-1][:1].isupper()]


def cycle_findings(graph: DependencyGraph, modules: list[ModuleInfo]) -> list[Finding]:
    path_of = {m.module: m.path for m in modules}
    findings: list[Finding] = []
    for cycle in graph.cycles:
        # anchor the finding on the most depended-upon module of the cycle
        anchor = max(cycle, key=lambda name: graph.nodes.get(name, {}).get("fan_in", 0))
        members = " ↔ ".join(cycle[:5]) + (f" … (+{len(cycle) - 5})" if len(cycle) > 5 else "")
        findings.append(Finding(
            kind="graph",
            rule="circular_dependency",
            severity="critical" if len(cycle) > 4 else "major",
            title=f"Circular dependency ({len(cycle)} modules)",
            message=(f"These modules form a closed loop: {members}. No module in the loop "
                     f"can be imported, tested or reused on its own. Extract what they share "
                     f"into a third module so the dependencies point one way."),
            file=path_of.get(anchor, anchor),
            line=1,
            symbol=anchor,
            metrics={"cycle": cycle, "size": len(cycle)},
        ))
    return findings
