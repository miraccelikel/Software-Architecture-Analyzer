"""SARIF 2.1.0 export.

SARIF is the format GitHub Code Scanning, Azure DevOps and most IDE problem
panels already understand. Emitting it means the findings land as annotations on
the exact line of a pull request, without anyone writing an integration: this is
the difference between a report someone has to open and a report that shows up
where the work happens.
"""

from __future__ import annotations

import hashlib
from typing import Any

SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
LEVELS = {"critical": "error", "major": "warning", "minor": "note", "info": "note"}
RANK = {"critical": 90.0, "major": 60.0, "minor": 30.0, "info": 10.0}

RULE_HELP = {
    "god_class": "Split the class along its responsibilities.",
    "large_class": "Watch which way this class is growing.",
    "long_method": "Break the method into parts that fit on a screen.",
    "too_many_parameters": "Group parameters that travel together into an object.",
    "magic_number": "Replace unnamed constants with named constants or an enum.",
    "deep_nesting": "Flatten with guard clauses and early returns.",
    "high_cyclomatic_complexity": "Split the function to reduce execution paths.",
    "duplicate_code": "Extract the shared behaviour into one place.",
    "dead_private_method": "Delete the dead code or make the behaviour reachable.",
    "srp_low_cohesion": "Move each disconnected group of methods into its own class.",
    "ocp_type_switch": "Use polymorphism or a Strategy instead of type checks.",
    "ocp_long_branch_chain": "Replace the branch chain with a lookup table or a Strategy.",
    "lsp_refused_bequest": "Prefer composition over inheritance here.",
    "lsp_narrowed_signature": "A subtype must not narrow the contract of its base.",
    "isp_fat_interface": "Split the interface into smaller role-based ones.",
    "dip_concrete_dependency": "Inject the dependency through an interface.",
    "circular_dependency": "Extract the shared part into a third module.",
    "volatile_complex_file": "Spend the refactoring budget here first.",
    "change_coupling": "Turn the implicit link into an explicit contract.",
    "singleton_global_state": "Make sure the global state is a deliberate choice.",
}


def _fingerprint(finding: dict) -> str:
    """Stable across line moves, so an unchanged finding is not re-reported."""
    metrics = finding.get("metrics") or {}
    discriminator = str(metrics.get("depends_on") or metrics.get("with") or "")
    raw = f"{finding['rule']}|{finding['file']}|{finding.get('symbol', '')}|{discriminator}"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def _rules(findings: list[dict]) -> tuple[list[dict], dict[str, int]]:
    index: dict[str, int] = {}
    rules: list[dict] = []
    for finding in findings:
        rule = finding["rule"]
        if rule in index:
            continue
        index[rule] = len(rules)
        rules.append({
            "id": rule,
            "name": "".join(part.capitalize() for part in rule.split("_")),
            "shortDescription": {"text": finding["title"]},
            "fullDescription": {"text": RULE_HELP.get(rule, finding["title"])},
            "help": {"text": RULE_HELP.get(rule, finding["title"])},
            "defaultConfiguration": {"level": LEVELS.get(finding["severity"], "note")},
            "properties": {"category": finding["kind"],
                           "tags": ["architecture", finding["kind"]]},
        })
    return rules, index


def _region(finding: dict) -> dict[str, Any]:
    region: dict[str, Any] = {"startLine": max(finding["line"], 1)}
    end = finding.get("end_line") or finding["line"]
    if end > finding["line"]:
        region["endLine"] = end
    snippet = (finding.get("snippet") or {}).get("lines") or []
    if snippet:
        region["snippet"] = {"text": "\n".join(snippet[:8])}
    return region


def build(report: dict) -> dict:
    """Render an ArchRay report as a SARIF log."""
    findings = report.get("findings", [])
    rules, index = _rules(findings)
    repository = report.get("repository", {})
    health = report.get("health", {})

    results = []
    for finding in findings:
        results.append({
            "ruleId": finding["rule"],
            "ruleIndex": index[finding["rule"]],
            "level": LEVELS.get(finding["severity"], "note"),
            "rank": RANK.get(finding["severity"], 10.0),
            "message": {"text": finding["message"]},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": finding["file"], "uriBaseId": "%SRCROOT%"},
                    "region": _region(finding),
                }
            }],
            "partialFingerprints": {"archrayFindingV1": _fingerprint(finding)},
            "properties": {"symbol": finding.get("symbol", ""),
                           **(finding.get("metrics") or {})},
        })

    return {
        "$schema": SCHEMA,
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "ArchRay",
                "version": report.get("meta", {}).get("version", "0"),
                "informationUri": "https://github.com/miraccelikel/software-architecture-analyzer",
                "rules": rules,
            }},
            "automationDetails": {"id": f"archray/{repository.get('language', 'python')}"},
            "results": results,
            "properties": {
                "healthScore": health.get("score"),
                "healthGrade": health.get("grade"),
                "repository": repository.get("name", ""),
            },
        }],
    }
