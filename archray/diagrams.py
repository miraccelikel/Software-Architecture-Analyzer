"""Diagrams generated from the analysis, as Mermaid source.

Mermaid is text, which makes these diagrams useful three times over: GitHub and
most editors render them inline, a reviewer can read the source itself, and an
agent can consume or rewrite them without an image pipeline.

Every diagram is capped in size on purpose. A class diagram with two hundred
boxes teaches nobody anything; the point is to show the part of the system a new
reader has to understand first.
"""

from __future__ import annotations

import re
from collections import defaultdict

from .graph import DependencyGraph, SymbolTable, class_relations
from .models import ClassInfo, ModuleInfo

MAX_CLASSES = 22
MAX_MODULES = 28
ARROWS = {"extends": "<|--", "creates": "-->", "uses": "..>"}
RELATION_LABEL = {"extends": "", "creates": "creates", "uses": "uses"}


# Mermaid keywords cannot be used as node identifiers — a module really can be
# called `graph.py`, and that silently breaks the whole diagram.
RESERVED = {"graph", "subgraph", "end", "class", "classdef", "click", "style",
            "linkstyle", "direction", "flowchart", "state", "note", "call", "href",
            "default", "interpolate", "o", "x"}


def _safe(name: str) -> str:
    """Mermaid identifiers: letters, digits and underscore."""
    cleaned = re.sub(r"[^\w]", "_", name)
    if not cleaned or cleaned[0].isdigit() or cleaned.lower() in RESERVED:
        cleaned = f"n_{cleaned}"
    return cleaned


def _importance(node: dict) -> int:
    return node.get("fan_in", 0) * 3 + node.get("fan_out", 0) + node.get("loc", 0) // 40


# --------------------------------------------------------------------------- #
def class_diagram(modules: list[ModuleInfo], symbols: SymbolTable,
                  class_graph: DependencyGraph, limit: int = MAX_CLASSES) -> str:
    """UML-ish class diagram of the most connected classes."""
    classes = {cls.qualname: cls for module in modules for cls in module.classes}
    if not classes:
        return ""

    ranked = sorted(classes.values(),
                    key=lambda c: -_importance(class_graph.nodes.get(c.qualname, {})))
    keep = {cls.qualname for cls in ranked[:limit]}

    lines = ["classDiagram", "  direction LR"]
    for cls in ranked[:limit]:
        label = _safe(cls.name)
        lines.append(f"  class {label} {{")
        if cls.is_abstract:
            lines.append("    <<abstract>>")
        for field in sorted(cls.instance_attrs | set(cls.class_attrs))[:4]:
            lines.append(f"    -{_safe(field)}")
        public = [m for m in cls.methods if not m.name.startswith("_")] or cls.methods
        for method in public[:5]:
            marker = "*" if method.is_abstract else ""
            lines.append(f"    +{_safe(method.name)}(){marker}")
        if len(public) > 5:
            lines.append(f"    +… {len(public) - 5} more methods")
        lines.append("  }")

    seen: set[tuple[str, str]] = set()
    for source, target, kind, _weight in class_relations(modules, symbols):
        if source.qualname not in keep or target.qualname not in keep:
            continue
        pair = (source.qualname, target.qualname)
        if pair in seen:
            continue
        seen.add(pair)
        arrow = ARROWS.get(kind, "..>")
        label = RELATION_LABEL.get(kind, "")
        suffix = f" : {label}" if label else ""
        if kind == "extends":
            lines.append(f"  {_safe(target.name)} {arrow} {_safe(source.name)}")
        else:
            lines.append(f"  {_safe(source.name)} {arrow} {_safe(target.name)}{suffix}")

    dropped = len(classes) - len(keep)
    if dropped > 0:
        lines.append(f"  note \"Showing the {len(keep)} most connected classes "
                     f"({dropped} more exist).\"")
    return "\n".join(lines)


def module_diagram(graph: DependencyGraph, limit: int = MAX_MODULES) -> str:
    """Module dependency flowchart, grouped by folder, cycles in red."""
    if not graph.nodes:
        return ""

    ranked = sorted(graph.nodes.values(), key=lambda n: -_importance(n))[:limit]
    keep = {node["id"] for node in ranked}

    groups: dict[str, list[dict]] = defaultdict(list)
    for node in ranked:
        folder = node["file"].rsplit("/", 1)[0] if "/" in node["file"] else "."
        groups[folder].append(node)

    lines = ["flowchart LR"]
    for folder, members in sorted(groups.items()):
        if folder != "." and len(groups) > 1:
            lines.append(f"  subgraph {_safe(folder)}[\"{folder}/\"]")
            indent = "    "
        else:
            indent = "  "
        for node in members:
            shape = f"([{node['label']}])" if node["fan_out"] == 0 else f"[{node['label']}]"
            lines.append(f"{indent}{_safe(node['id'])}{shape}")
        if folder != "." and len(groups) > 1:
            lines.append("  end")

    in_cycle = {node["id"] for node in ranked if node["in_cycle"]}
    for (source, target), weight in sorted(graph.edges.items()):
        if source not in keep or target not in keep:
            continue
        arrow = "==>" if weight >= 4 else "-->"
        lines.append(f"  {_safe(source)} {arrow} {_safe(target)}")

    lines.append("  classDef cycle fill:#3b1512,stroke:#ff5c4d,color:#ffd9d3")
    lines.append("  classDef hot fill:#3a2f10,stroke:#e8b23c,color:#ffeec2")
    if in_cycle:
        lines.append(f"  class {','.join(_safe(n) for n in sorted(in_cycle))} cycle")
    hot = [node["id"] for node in ranked
           if node["findings"] >= 3 and node["id"] not in in_cycle]
    if hot:
        lines.append(f"  class {','.join(_safe(n) for n in sorted(hot))} hot")
    return "\n".join(lines)


def package_diagram(graph: DependencyGraph) -> str:
    """One box per folder — the ten-thousand-foot view."""
    folders: dict[str, dict] = defaultdict(lambda: {"loc": 0, "modules": 0, "findings": 0})
    owner: dict[str, str] = {}
    for node in graph.nodes.values():
        folder = node["file"].rsplit("/", 1)[0] if "/" in node["file"] else "."
        owner[node["id"]] = folder
        bucket = folders[folder]
        bucket["loc"] += node["loc"]
        bucket["modules"] += 1
        bucket["findings"] += node["findings"]

    if len(folders) < 2:
        return ""

    edges: dict[tuple[str, str], int] = defaultdict(int)
    for (source, target), weight in graph.edges.items():
        a, b = owner.get(source), owner.get(target)
        if a and b and a != b:
            edges[(a, b)] += weight

    lines = ["flowchart TD"]
    for folder, stats in sorted(folders.items()):
        lines.append(f"  {_safe(folder)}[\"{folder}/<br/>{stats['modules']} modules · "
                     f"{stats['loc']} lines · {stats['findings']} findings\"]")
    for (a, b), weight in sorted(edges.items()):
        lines.append(f"  {_safe(a)} -->|{weight}| {_safe(b)}")
    return "\n".join(lines)


def build(modules: list[ModuleInfo], symbols: SymbolTable,
          module_graph: DependencyGraph, class_graph: DependencyGraph) -> dict[str, str]:
    return {
        "classes": class_diagram(modules, symbols, class_graph),
        "modules": module_diagram(module_graph),
        "packages": package_diagram(module_graph),
    }
