"""A reading order for someone opening this repository for the first time.

Given the dependency graph we can answer the question a newcomer actually has —
*where do I start?* — instead of the question a file tree answers, which is
*what is here, alphabetically?*

The tour is built from four signals: what nothing depends on (entry points),
what everything depends on (foundations), how deep each module sits in the
dependency stack (reading order), and which abstractions organise the design.
"""

from __future__ import annotations

from collections import defaultdict

from .graph import DependencyGraph
from .models import ModuleInfo

ENTRY_NAMES = ("main", "__main__", "cli", "app", "index", "server", "program", "wsgi", "asgi")
ROLE_HINTS = {
    "model": "data models", "models": "data models", "entity": "entities",
    "entities": "entities", "domain": "business rules", "core": "core",
    "service": "business logic", "services": "business logic", "handler": "request handlers",
    "controller": "endpoints", "controllers": "endpoints", "api": "public interface",
    "routes": "routing", "view": "presentation", "views": "presentation", "ui": "user interface",
    "repository": "data access", "repositories": "data access", "dao": "data access",
    "db": "data access", "storage": "data access", "infra": "infrastructure",
    "infrastructure": "infrastructure", "adapter": "external systems",
    "adapters": "external systems", "client": "external systems",
    "util": "helpers", "utils": "helpers", "helpers": "helpers",
    "common": "shared code", "shared": "shared code", "config": "configuration",
    "parser": "parsing", "parsing": "parsing", "lexer": "parsing",
    "render": "output", "renderer": "output", "report": "reporting",
    "test": "tests", "cmd": "commands", "internal": "internals",
}


def _levels(graph: DependencyGraph) -> dict[str, int]:
    """Depth in the dependency stack: 0 = depends on nothing else in the project."""
    adjacency = graph.adjacency()
    level = {node: 0 for node in graph.nodes}
    for _ in range(min(len(level), 40)):          # cycles cannot converge, so cap
        changed = False
        for node, targets in adjacency.items():
            deepest = max((level[t] + 1 for t in targets if t in level and t != node),
                          default=0)
            if deepest > level[node]:
                level[node] = deepest
                changed = True
        if not changed:
            break
    return level


def _role_of(path: str) -> str:
    parts = [p.lower() for p in path.replace("\\", "/").split("/")]
    stem = parts[-1].rsplit(".", 1)[0]
    for token in (*parts[:-1], stem):
        for keyword, role in ROLE_HINTS.items():
            if token == keyword or token.endswith("_" + keyword) or keyword in token.split("_"):
                return role
    return ""


def build(modules: list[ModuleInfo], graph: DependencyGraph,
          class_graph: DependencyGraph, patterns: list[dict],
          hotspots: list[dict]) -> dict:
    if not graph.nodes:
        return {}

    level = _levels(graph)
    nodes = list(graph.nodes.values())

    entry_points = [n for n in nodes
                    if n["fan_in"] == 0 and (n["classes"] or n["functions"])]
    entry_points.sort(key=lambda n: (n["label"].lower() not in ENTRY_NAMES, -n["loc"]))

    foundations = sorted((n for n in nodes if n["dependents"] > 0),
                         key=lambda n: (-n["dependents"], -n["fan_in"]))[:5]

    reading_order = sorted(nodes, key=lambda n: (level[n["id"]], -n["fan_in"]))
    layers: dict[int, list[dict]] = defaultdict(list)
    for node in reading_order:
        layers[level[node["id"]]].append(node)

    folders: dict[str, dict] = defaultdict(
        lambda: {"modules": 0, "loc": 0, "findings": 0, "role": ""})
    for node in nodes:
        folder = node["file"].rsplit("/", 1)[0] if "/" in node["file"] else "."
        bucket = folders[folder]
        bucket["modules"] += 1
        bucket["loc"] += node["loc"]
        bucket["findings"] += node["findings"]
        if folder != ".":
            bucket["role"] = bucket["role"] or _role_of(node["file"])

    abstractions = [n for n in class_graph.nodes.values()
                    if n.get("is_abstract") and n["fan_in"] > 0]
    abstractions.sort(key=lambda n: -n["fan_in"])

    return {
        "entry_points": [_brief(n) for n in entry_points[:5]],
        "foundations": [_brief(n) for n in foundations],
        "layers": [
            {"level": depth, "modules": [_brief(n) for n in members[:8]],
             "total": len(members)}
            for depth, members in sorted(layers.items())[:6]
        ],
        "folders": [
            {"path": path, **stats}
            for path, stats in sorted(folders.items(), key=lambda kv: -kv[1]["loc"])[:12]
        ],
        "abstractions": [
            {"name": n["label"], "file": n["file"], "used_by": n["fan_in"]}
            for n in abstractions[:6]
        ],
        "patterns": [
            {"pattern": p["pattern"], "participants": p["participants"][:3], "file": p["file"]}
            for p in patterns[:6]
        ],
        "danger_zones": hotspots[:5],
    }


def _brief(node: dict) -> dict:
    return {"module": node["id"], "file": node["file"], "loc": node["loc"],
            "fan_in": node["fan_in"], "fan_out": node["fan_out"],
            "dependents": node.get("dependents", 0),
            "findings": node["findings"], "role": _role_of(node["file"])}


# --------------------------------------------------------------------------- #
def to_markdown(report: dict) -> str:
    """A hand-out a new contributor can read in five minutes."""
    tour = report.get("tour") or {}
    if not tour:
        return "# Codebase tour\n\nNo tour could be generated for this repository.\n"

    repository = report.get("repository", {})
    health = report["health"]
    summary = report["summary"]
    diagrams = report.get("diagrams", {})
    out: list[str] = []

    out.append(f"# {repository.get('name', 'Project')} — codebase tour")
    out.append("")
    out.append(f"*{summary['modules']} modules · {summary['classes']} classes · "
               f"{summary['sloc']} lines of code · health {health['score']}/100 "
               f"({health['grade']})*")
    out.append("")
    out.append("Generated by ArchRay from the dependency graph. Nothing here was written "
               "by hand, so it can be regenerated whenever the code changes.")

    if diagrams.get("packages"):
        out += ["", "## Bird's-eye view", "", "```mermaid", diagrams["packages"], "```"]

    out += ["", "## Where to start", ""]
    if tour["entry_points"]:
        out.append("**Entry points** — nothing depends on these; execution starts here:")
        out.append("")
        for item in tour["entry_points"]:
            role = f" · {item['role']}" if item["role"] else ""
            out.append(f"- `{item['file']}` ({item['loc']} lines{role})")
        out.append("")
    if tour["foundations"]:
        out.append("**Foundations** — the most depended-upon modules; the rest will not "
                   "make sense until these do:")
        out.append("")
        for item in tour["foundations"]:
            role = f" · {item['role']}" if item["role"] else ""
            out.append(f"- `{item['file']}` — {item['dependents']} modules depend on it{role}")

    if tour["layers"]:
        out += ["", "## Reading order", "",
                "Modules by dependency depth: layer 0 stands on its own, each layer above "
                "uses the ones below it.", ""]
        for layer in tour["layers"]:
            names = ", ".join(f"`{m['file']}`" for m in layer["modules"])
            extra = f" (+{layer['total'] - len(layer['modules'])} more)" \
                if layer["total"] > len(layer["modules"]) else ""
            out.append(f"**Layer {layer['level']}** — {names}{extra}")
            out.append("")

    if tour["folders"]:
        out += ["## Folders", "", "| Folder | Modules | Lines | Findings | Role |",
                "|---|---:|---:|---:|---|"]
        for folder in tour["folders"]:
            out.append(f"| `{folder['path']}/` | {folder['modules']} | {folder['loc']} | "
                       f"{folder['findings']} | {folder['role'] or '—'} |")

    if tour["abstractions"] or tour["patterns"]:
        out += ["", "## What holds the design together", ""]
        for item in tour["abstractions"]:
            out.append(f"- **{item['name']}** (`{item['file']}`) — an abstraction used in "
                       f"{item['used_by']} places")
        for item in tour["patterns"]:
            participants = ", ".join(item["participants"])
            out.append(f"- **{item['pattern']}** — {participants} (`{item['file']}`)")

    if diagrams.get("classes"):
        out += ["", "## Class relationships", "", "```mermaid", diagrams["classes"], "```"]
    if diagrams.get("modules"):
        out += ["", "## Module dependencies", "", "```mermaid", diagrams["modules"], "```",
                "", "*Red boxes are part of a dependency cycle; yellow boxes carry three or "
                "more findings.*"]

    if tour["danger_zones"]:
        out += ["", "## Handle with care", "",
                "| File | Lines | Complexity | Findings |", "|---|---:|---:|---:|"]
        for zone in tour["danger_zones"]:
            out.append(f"| `{zone['file']}` | {zone['loc']} | {zone['complexity']} | "
                       f"{zone['findings']} |")

    out += ["", "---", f"*ArchRay {report['meta']['version']} · "
            f"{report['meta']['generated_at'][:10]}*", ""]
    return "\n".join(out)
