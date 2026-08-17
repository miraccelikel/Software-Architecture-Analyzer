"""A review sheet for a structural diff.

The intended reader is someone reviewing code they did not write — increasingly,
code an assistant wrote — who needs to know what actually changed in the shape
of the system before reading a single line of the text diff.
"""

from __future__ import annotations

from .codediff import to_unified

LEVEL_MARK = {"warning": "⚠️", "info": "•"}


def to_markdown(report: dict) -> str:
    changes = report.get("changes")
    if not changes:
        return "# Structural changes\n\nNothing to compare against.\n"

    repository = report.get("repository", {})
    functions, classes = changes["functions"], changes["classes"]
    out: list[str] = []

    out.append(f"# What changed — {repository.get('name', 'project')}")
    out.append("")
    out.append(f"Compared against `{changes['revision']}`. **{changes['headline']}**")
    out.append("")
    out.append(f"Architecture score {changes['baseline_score']} → **{changes['score']}** "
               f"({changes['score_delta']:+})")

    if changes["highlights"]:
        out += ["", "## Read these first", ""]
        for note in changes["highlights"]:
            location = f" — `{note['file']}:{note['line']}`" if note["file"] else ""
            out.append(f"- {LEVEL_MARK.get(note['level'], '•')} {note['text']}{location}")

    counts = functions["counts"]
    out += ["", "## Functions", "",
            f"`+{counts['added']} added` · `~{counts['modified']} rewritten` · "
            f"`-{counts['removed']} removed`", ""]
    if functions["modified"]:
        out += ["| Function | Complexity | Lines | File |", "|---|---|---|---|"]
        for item in functions["modified"][:15]:
            arrow = "↑" if item["complexity_delta"] > 0 else "↓" if item["complexity_delta"] < 0 else "="
            out.append(f"| `{item['name']}` | {item['complexity_before']} → "
                       f"{item['complexity_after']} {arrow} | {item['loc_before']} → "
                       f"{item['loc_after']} | `{item['file']}:{item['line']}` |")
        out.append("")
    if functions["added"]:
        out.append("**Added:** " + ", ".join(f"`{item['qualname']}`"
                                             for item in functions["added"][:12]))
        out.append("")
    if functions["removed"]:
        out.append("**Removed:** " + ", ".join(f"`{item['qualname']}`"
                                               for item in functions["removed"][:12]))
        out.append("")

    class_counts = classes["counts"]
    if any(class_counts.values()):
        out += ["## Classes", "",
                f"`+{class_counts['added']} added` · `~{class_counts['modified']} changed` · "
                f"`-{class_counts['removed']} removed`", ""]
        for item in classes["modified"][:10]:
            if item["methods_before"] != item["methods_after"]:
                out.append(f"- `{item['name']}` — methods {item['methods_before']} → "
                           f"{item['methods_after']}")
            if item["bases_before"] != item["bases_after"]:
                out.append(f"- `{item['name']}` — base classes "
                           f"{item['bases_before']} → {item['bases_after']}")
        for item in classes["added"][:10]:
            out.append(f"- new class `{item['qualname']}` "
                       f"({item['methods']} methods, `{item['file']}`)")
        out.append("")

    code = changes.get("code") or []
    if code:
        out += ["## The code itself", ""]
        for diff in code[:8]:
            label = {"modified": "rewritten", "added": "added", "removed": "removed"}[diff["kind"]]
            complexity = ""
            if diff["kind"] == "modified":
                complexity = (f" · complexity {diff['complexity_before']} → "
                              f"{diff['complexity_after']}")
            out += [f"<details><summary><code>{diff['qualname']}</code> — {label}"
                    f" (+{diff['stats']['added']}/-{diff['stats']['removed']}){complexity}"
                    f"</summary>", "", "```diff"]
            out.append(to_unified(diff) or "(no textual change)")
            out += ["```", "", "</details>", ""]

    edges = changes["edges"]
    if edges["added"] or edges["removed"]:
        out += ["## Dependencies", ""]
        for edge in edges["added"][:15]:
            out.append(f"- **new:** `{edge['source']}` → `{edge['target']}`")
        for edge in edges["removed"][:10]:
            out.append(f"- removed: `{edge['source']}` → `{edge['target']}`")
        out.append("")

    findings = changes["findings"]
    if findings["new"] or findings["fixed"]:
        out += ["## Findings", "", f"{findings['verdict']}", ""]
        for item in findings["new"][:10]:
            out.append(f"- 🔴 new {item['severity']}: {item['title']} — "
                       f"`{item['file']}:{item['line']}`")
        for item in findings["fixed"][:6]:
            out.append(f"- 🟢 fixed: {item['title']} — `{item['symbol'] or item['file']}`")
        out.append("")

    out += ["---", f"*ArchRay {report['meta']['version']}*", ""]
    return "\n".join(out)
