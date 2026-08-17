"""The pipeline: ingest → parse → index → analyse → aggregate."""

from __future__ import annotations

import time
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone

from . import graph as graph_mod
from . import (bindings, diagrams, duplication, history, ingest, parsing,
               patterns, scoring, smells, snippets, solid, sources,
               suppression, tour)
from .config import Thresholds
from .models import Finding, ModuleInfo
from .treesitter_frontend import TreeSitterUnavailable

VERSION = "0.1.0"


def analyze_source(source: str, language: str = "auto",
                   thresholds: Thresholds | None = None,
                   include_tests: bool = False,
                   history_commits: int = 0) -> dict:
    """Analyse a GitHub URL or a local path and return the report dictionary.

    `history_commits > 0` also reads the git log, which needs a deeper clone.
    """
    thresholds = thresholds or Thresholds()
    started = time.perf_counter()
    repo = ingest.open_source(source, depth=max(history_commits, 1) if history_commits else 1)
    try:
        grouped = ingest.plan(repo, language=language, include_tests=include_tests,
                              exclude_paths=thresholds.exclude_paths)
        if not grouped:
            raise RuntimeError(
                f"No analysable source files found in '{repo.name}'"
                + ("" if language == "auto" else f" for language '{language}'")
            )

        modules = []
        files = []
        unsupported: list[dict] = []
        for detected, paths in grouped.items():
            try:
                parsed = parse_files(repo.root, paths, detected)
            except TreeSitterUnavailable as exc:
                # one missing grammar must not cost the languages that do work:
                # skip it, say so, and carry on
                if language != "auto":
                    raise
                unsupported.append({"language": detected, "files": len(paths),
                                    "reason": str(exc)})
                continue
            for module in parsed:
                module.language = detected
            modules.extend(parsed)
            files.extend(paths)

        if not modules:
            detail = "; ".join(item["reason"] for item in unsupported)
            raise RuntimeError(
                f"Nothing could be parsed in '{repo.name}'."
                + (f" {detail}" if detail else "")
            )
        evolution = {}
        if history_commits:
            tracked = {m.path for m in modules} | {
                path for m in modules for path in m.extra_sources}
            if history.available(repo.root):
                evolution = history.collect(repo.root, tracked, history_commits)
            else:
                evolution = {"unavailable": True}
        report = build_report(modules, thresholds, evolution, repo.root)
        report["repository"] = {
            "name": repo.name,
            "url": repo.url,
            "ref": repo.ref,
            "language": language,
            "languages": [
                {"language": name, "label": ingest.LANGUAGE_LABELS.get(name, name),
                 "files": len(paths)}
                for name, paths in grouped.items()
            ],
            "files_analyzed": len(files),
            "include_tests": include_tests,
            "unsupported": unsupported,
        }
        report["meta"]["duration_ms"] = int((time.perf_counter() - started) * 1000)
        return report
    finally:
        repo.cleanup()


def parse_files(root, files, language: str):
    """Dispatch to the front-end that understands this language.

    Raises TreeSitterUnavailable when the grammar for `language` is not
    installed, which the caller may choose to survive.
    """
    if language == "python":
        return parsing.parse_repository(root, files)
    from .treesitter_frontend import parse_repository as ts_parse
    return ts_parse(root, files, language)


def build_report(modules: list[ModuleInfo], thresholds: Thresholds,
                 evolution: dict | None = None, root: Path | None = None) -> dict:
    symbols = graph_mod.SymbolTable(modules)
    dependency_graph = graph_mod.build_graph(modules, symbols)

    findings: list[Finding] = []
    findings += smells.run(modules, thresholds)
    findings += duplication.run(modules, thresholds)
    findings += solid.run(modules, symbols, thresholds)
    pattern_matches, pattern_findings = patterns.run(modules, symbols, thresholds)
    findings += pattern_findings
    findings += graph_mod.cycle_findings(dependency_graph, modules)

    # contracts that cross a language boundary are checked by no compiler
    contracts = bindings.resolve(modules)
    findings += bindings.findings(contracts)

    module_of = {m.path: m.module for m in modules}
    for module in modules:
        for path in module.extra_sources:
            module_of[path] = module.module
    complexity_of: dict[str, int] = {}
    for module in modules:
        for func in module.all_functions:
            complexity_of[func.file] = complexity_of.get(func.file, 0) + func.complexity

    evolution_summary = {}
    if evolution and not evolution.get("unavailable"):
        evolution_summary = history.summarise(evolution, module_of, complexity_of)
        findings += history.findings(evolution_summary, module_of)

    findings, suppressed = suppression.apply(findings, modules, thresholds.ignore_rules)
    findings.sort(key=lambda f: (f.file, f.line))
    snippets.attach(findings, modules)

    by_module: Counter[str] = Counter()
    penalty_by_module: Counter[str] = Counter()
    path_to_module = {m.path: m.module for m in modules}
    for finding in findings:
        module_name = path_to_module.get(finding.file)
        if module_name:
            by_module[module_name] += 1
            penalty_by_module[module_name] += finding.weight

    language_of = {m.module: m.language for m in modules}
    for module_name, node in dependency_graph.nodes.items():
        node["language"] = language_of.get(module_name, "")
        node["findings"] = by_module.get(module_name, 0)
        node["score_penalty"] = round(penalty_by_module.get(module_name, 0.0), 1)

    class_graph = graph_mod.build_class_graph(modules, symbols)
    _count_class_findings(class_graph, modules, findings)

    health = scoring.compute(modules, findings, dependency_graph.cycles, thresholds)
    pattern_dicts = [p.to_dict() for p in pattern_matches]
    hotspots = _hotspots(modules, by_module)
    drawings = diagrams.build(modules, symbols, dependency_graph, class_graph)
    guide = tour.build(modules, dependency_graph, class_graph, pattern_dicts, hotspots)

    classes = [c for m in modules for c in m.classes]
    functions = [f for m in modules for f in m.all_functions]

    return {
        "meta": {
            "tool": "ArchRay",
            "version": VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "thresholds": thresholds.to_dict(),
        },
        "health": health,
        "summary": {
            "languages": _language_breakdown(modules, by_module),
            "modules": len(modules),
            "classes": len(classes),
            "functions": len(functions),
            "loc": sum(m.loc for m in modules),
            "sloc": sum(m.sloc for m in modules),
            "findings": len(findings),
            "by_severity": dict(Counter(f.severity for f in findings)),
            "by_kind": dict(Counter(f.kind for f in findings)),
            "by_rule": dict(Counter(f.rule for f in findings).most_common()),
            "patterns": len(pattern_matches),
            "cycles": len(dependency_graph.cycles),
            "suppressed": suppressed,
        },
        "inventory": _inventory(modules),
        "sources": sources.collect(root, modules, [f.to_dict() for f in findings])
                   if root is not None else {"files": {}, "tree": [], "skipped": 0},
        "top_debt": scoring.rank_debt(findings, limit=5),
        "bindings": bindings.summarise(contracts),
        "history": evolution_summary,
        "diagrams": drawings,
        "tour": guide,
        "findings": [f.to_dict() for f in findings],
        "patterns": pattern_dicts,
        "graph": {
            "nodes": list(dependency_graph.nodes.values()),
            "edges": [{"source": s, "target": t, "weight": w}
                      for (s, t), w in sorted(dependency_graph.edges.items())],
            "cycles": dependency_graph.cycles,
            "class_nodes": list(class_graph.nodes.values()),
            "class_edges": [{"source": src, "target": dst, "weight": weight,
                             "kind": class_graph.edge_kinds.get((src, dst), "uses")}
                            for (src, dst), weight in sorted(class_graph.edges.items())],
            "class_cycles": class_graph.cycles,
        },
        "hotspots": hotspots,
        "modules": [
            {"path": m.path, "module": m.module, "loc": m.loc, "sloc": m.sloc,
             "classes": [c.to_dict() for c in m.classes],
             "functions": [f.to_dict() for f in m.functions],
             "language": m.language,
             "findings": by_module.get(m.module, 0),
             "parse_error": m.parse_error}
            for m in modules
        ],
    }


def _count_class_findings(class_graph, modules: list[ModuleInfo],
                          findings: list[Finding]) -> None:
    """Map each finding onto the class whose body contains it."""
    spans = [(cls.file, cls.line, cls.end_line, cls.qualname)
             for module in modules for cls in module.classes]
    for finding in findings:
        for file, start, end, qualname in spans:
            if finding.file == file and start <= finding.line <= end:
                node = class_graph.nodes.get(qualname)
                if node:
                    node["findings"] += 1
                    node["score_penalty"] = round(node["score_penalty"] + finding.weight, 1)
                break


def _inventory(modules: list[ModuleInfo]) -> dict:
    """Every function and class with its structural fingerprint.

    This is what makes a *semantic* diff possible: comparing two inventories
    tells you which functions were added, removed or rewritten, instead of which
    lines moved.
    """
    functions = [{
        "qualname": func.qualname, "name": func.name, "file": func.file,
        "line": func.line, "loc": func.loc, "complexity": func.complexity,
        "params": len(func.params), "class_name": func.class_name,
        "fingerprint": func.fingerprint,
    } for module in modules for func in module.all_functions]

    classes = [{
        "qualname": cls.qualname, "name": cls.name, "file": cls.file,
        "line": cls.line, "loc": cls.loc, "methods": cls.method_count,
        "bases": cls.bases, "is_abstract": cls.is_abstract, "lcom4": cls.lcom4,
    } for module in modules for cls in module.classes]

    return {"functions": functions, "classes": classes,
            "modules": [{"module": m.module, "file": m.path, "language": m.language,
                         "sloc": m.sloc} for m in modules]}


def _language_breakdown(modules: list[ModuleInfo], by_module: Counter) -> list[dict]:
    """Per-language totals — a mixed repository deserves a mixed summary."""
    buckets: dict[str, dict] = {}
    for module in modules:
        name = module.language or "unknown"
        bucket = buckets.setdefault(name, {"language": name, "modules": 0, "sloc": 0,
                                           "classes": 0, "findings": 0})
        bucket["modules"] += 1
        bucket["sloc"] += module.sloc
        bucket["classes"] += len(module.classes)
        bucket["findings"] += by_module.get(module.module, 0)
    return sorted(buckets.values(), key=lambda b: -b["sloc"])


def _hotspots(modules: list[ModuleInfo], by_module: Counter) -> list[dict]:
    """Files where size and problem count meet — the riskiest places to touch."""
    rows = []
    for module in modules:
        complexity = sum(f.complexity for f in module.all_functions)
        issues = by_module.get(module.module, 0)
        if not issues:
            continue
        rows.append({
            "file": module.path,
            "module": module.module,
            "loc": module.loc,
            "complexity": complexity,
            "findings": issues,
            "risk": round(issues * (1 + complexity / 50) * (1 + module.loc / 400), 1),
        })
    rows.sort(key=lambda r: -r["risk"])
    return rows[:12]
