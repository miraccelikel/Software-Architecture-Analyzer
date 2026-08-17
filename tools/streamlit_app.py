"""Streamlit explorer for ArchRay reports.

This deliberately does *not* replace the HTML dashboard, and the distinction is
worth stating. The report is one self-contained file: it survives being attached
to a CI run, emailed, opened offline and printed to PDF, and it describes exactly
one analysis. That is the right shape for a deliverable.

What a single file cannot do is compare many analyses. This app fills that gap:
point it at a folder of `.json` reports (a CI artifact directory, a series of
nightly runs, every service in an organisation) and it answers questions that
span them — which project carries the most debt per thousand lines, which rules
fire everywhere, how one project's score moved across runs.

    pip install "archray[explore]"
    streamlit run tools/streamlit_app.py -- --reports ./reports
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

SEVERITY_ORDER = ["critical", "major", "minor", "info"]
SEVERITY_COLOR = {"critical": "#C0392B", "major": "#D68910",
                  "minor": "#2980B9", "info": "#7F8C8D"}
GRADE_COLOR = {"A": "#2ECC71", "B": "#2ECC71", "C": "#F1C40F",
               "D": "#E67E22", "F": "#E74C3C"}


# --------------------------------------------------------------------------- #
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--reports", default="reports",
                        help="folder holding ArchRay JSON reports")
    known, _ = parser.parse_known_args(sys.argv[1:])
    return known


@st.cache_data(show_spinner=False)
def load_reports(folder: str) -> dict[str, dict]:
    """Read every ArchRay JSON in a folder, newest first."""
    root = Path(folder)
    if not root.is_dir():
        return {}
    reports: dict[str, dict] = {}
    for path in sorted(root.glob("*.json"), key=lambda p: -p.stat().st_mtime):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if "health" not in payload or "findings" not in payload:
            continue          # some other JSON that happens to live here
        label = payload.get("repository", {}).get("name") or path.stem
        reports[f"{label}  ({path.name})"] = payload
    return reports


def findings_frame(report: dict) -> pd.DataFrame:
    rows = [{
        "severity": f["severity"], "kind": f["kind"], "rule": f["rule"],
        "title": f["title"], "symbol": f.get("symbol", ""),
        "file": f["file"], "line": f["line"],
        "folder": f["file"].rsplit("/", 1)[0] if "/" in f["file"] else ".",
        "message": f["message"],
    } for f in report.get("findings", [])]
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["severity"] = pd.Categorical(frame["severity"], SEVERITY_ORDER, ordered=True)
    return frame


def portfolio_frame(reports: dict[str, dict]) -> pd.DataFrame:
    rows = []
    for label, report in reports.items():
        health, summary = report["health"], report["summary"]
        severities = summary.get("by_severity", {})
        kloc = max(summary.get("sloc", 0) / 1000, 0.1)
        rows.append({
            "report": label,
            "project": report.get("repository", {}).get("name", label),
            "score": health["score"], "grade": health["grade"],
            "languages": ", ".join(item["language"]
                                   for item in summary.get("languages", [])) or "—",
            "sloc": summary.get("sloc", 0),
            "findings": summary.get("findings", 0),
            "critical": severities.get("critical", 0),
            "major": severities.get("major", 0),
            "per_kloc": round(summary.get("findings", 0) / kloc, 1),
            "cycles": summary.get("cycles", 0),
            "patterns": summary.get("patterns", 0),
            "generated": report.get("meta", {}).get("generated_at", "")[:16],
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
def render_overview(reports: dict[str, dict]) -> None:
    st.subheader("Portfolio")
    frame = portfolio_frame(reports)
    st.caption("Every report in the folder. `per_kloc` is the comparable number — "
               "a large project is not unhealthy merely for being large.")

    st.dataframe(
        frame.sort_values("score"),
        use_container_width=True, hide_index=True,
        column_config={
            "score": st.column_config.ProgressColumn("score", min_value=0, max_value=100,
                                                     format="%.1f"),
            "sloc": st.column_config.NumberColumn("lines", format="%d"),
            "per_kloc": st.column_config.NumberColumn("findings / kloc"),
        },
    )

    left, right = st.columns(2)
    with left:
        st.markdown("**Debt density**")
        st.bar_chart(frame.set_index("project")["per_kloc"], color="#E67E22")
    with right:
        st.markdown("**Health score**")
        st.bar_chart(frame.set_index("project")["score"], color="#48C4E8")

    rules = {}
    for report in reports.values():
        for rule, count in report["summary"].get("by_rule", {}).items():
            rules[rule] = rules.get(rule, 0) + count
    if rules:
        st.markdown("**Rules firing across the whole portfolio**")
        st.caption("A rule that fires everywhere is usually a house-style decision, "
                   "not a discovery — that is the one to configure away.")
        st.bar_chart(pd.Series(rules).sort_values(ascending=False).head(12))


def render_project(report: dict) -> None:
    health, summary = report["health"], report["summary"]
    columns = st.columns(5)
    columns[0].metric("Score", f"{health['score']}", health["grade"])
    columns[1].metric("Findings", summary["findings"],
                      f"{summary['by_severity'].get('critical', 0)} critical")
    columns[2].metric("Lines", f"{summary['sloc']:,}")
    columns[3].metric("Patterns", summary["patterns"])
    columns[4].metric("Cycles", summary["cycles"])
    st.caption(health["verdict"])

    dimensions = pd.DataFrame(health["dimensions"]).set_index("label")["score"]
    st.bar_chart(dimensions, horizontal=True)

    languages = summary.get("languages") or []
    if len(languages) > 1:
        st.markdown("**Languages**")
        st.dataframe(pd.DataFrame(languages), use_container_width=True, hide_index=True)

    unsupported = report.get("repository", {}).get("unsupported") or []
    for item in unsupported:
        st.warning(f"`{item['language']}` was skipped ({item['files']} files): "
                   f"{item['reason']}")


def render_findings(report: dict) -> None:
    frame = findings_frame(report)
    if frame.empty:
        st.success("No findings.")
        return

    controls = st.columns([1, 1, 2])
    severities = controls[0].multiselect(
        "Severity", SEVERITY_ORDER,
        default=[s for s in SEVERITY_ORDER if s in set(frame["severity"])])
    kinds = controls[1].multiselect("Kind", sorted(frame["kind"].unique()),
                                    default=sorted(frame["kind"].unique()))
    needle = controls[2].text_input("Search file, symbol or rule")

    filtered = frame[frame["severity"].isin(severities) & frame["kind"].isin(kinds)]
    if needle:
        haystack = (filtered["file"] + " " + filtered["symbol"] + " " +
                    filtered["rule"] + " " + filtered["title"]).str.lower()
        filtered = filtered[haystack.str.contains(needle.lower())]

    st.caption(f"{len(filtered)} of {len(frame)} findings")
    left, right = st.columns(2)
    with left:
        st.markdown("**By rule**")
        st.bar_chart(filtered["rule"].value_counts().head(12))
    with right:
        st.markdown("**By folder**")
        st.bar_chart(filtered["folder"].value_counts().head(12))

    st.dataframe(
        filtered[["severity", "title", "symbol", "file", "line", "rule"]],
        use_container_width=True, hide_index=True, height=380,
    )

    if not filtered.empty:
        with st.expander("Read a finding in full"):
            index = st.selectbox(
                "Finding", filtered.index,
                format_func=lambda i: f"{filtered.loc[i, 'title']} — "
                                      f"{filtered.loc[i, 'file']}:{filtered.loc[i, 'line']}")
            row = filtered.loc[index]
            st.markdown(f"**{row['title']}** · `{row['rule']}` · {row['severity']}")
            st.write(row["message"])


def render_structure(report: dict) -> None:
    nodes = report.get("graph", {}).get("nodes", [])
    if not nodes:
        st.info("No dependency graph in this report.")
        return

    frame = pd.DataFrame(nodes)
    st.markdown("**Coupling**")
    st.caption("Instability is fan-out over total coupling: 0 is depended upon and stable, "
               "1 depends on everything and is free to change.")
    st.scatter_chart(frame, x="instability", y="loc", size="findings", color="#48C4E8")

    st.dataframe(
        frame[["id", "file", "loc", "dependents", "dependencies", "instability",
               "max_complexity", "findings"]]
        .sort_values("findings", ascending=False),
        use_container_width=True, hide_index=True, height=320,
    )

    diagrams = report.get("diagrams") or {}
    if diagrams:
        choice = st.selectbox("Diagram", [k for k, v in diagrams.items() if v])
        st.code(diagrams[choice], language="mermaid")
        st.caption("Mermaid source — paste it into a README or a wiki page.")


def render_history(report: dict) -> None:
    evolution = report.get("history") or {}
    if not evolution:
        st.info("Run `archray … --history 400` to add change frequency and coupling.")
        return

    st.caption(f"{evolution['commits_scanned']} commits · {evolution['authors']} authors")
    hotspots = pd.DataFrame(evolution["hotspots"])
    st.markdown("**Refactoring targets** — complexity × change frequency")
    st.scatter_chart(hotspots, x="revisions", y="complexity", size="risk", color="#E67E22")
    st.dataframe(hotspots, use_container_width=True, hide_index=True, height=280)

    coupling = evolution.get("coupling") or []
    if coupling:
        st.markdown("**Files that change together**")
        st.caption("No import connects these; the coupling is invisible to the graph.")
        st.dataframe(pd.DataFrame([{
            "file A": item["files"][0], "file B": item["files"][1],
            "degree": item["degree"], "shared commits": item["shared_commits"],
            "same module": item["same_module"],
        } for item in coupling]), use_container_width=True, hide_index=True)


def render_bindings(report: dict) -> None:
    payload = report.get("bindings") or {}
    if not payload:
        st.info("No cross-language bindings were found in this project.")
        return
    counts = payload["counts"]
    columns = st.columns(3)
    columns[0].metric("Satisfied", counts["satisfied"])
    columns[1].metric("Mismatched", counts["mismatch"])
    columns[2].metric("Dangling", counts["dangling"])

    rows = [{
        "status": item["status"], "symbol": item["symbol"], "library": item["library"],
        "managed": item["managed"]["signature"],
        "native": (item["native"] or {}).get("signature", "—"),
        "problem": "; ".join(item["problems"]) or "—",
    } for item in payload["bindings"]]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_changes(report: dict) -> None:
    changes = report.get("changes")
    if not changes:
        st.info("Run `archray … --changes HEAD` to add a structural diff.")
        return

    st.markdown(f"**{changes['headline']}**")
    counts = changes["functions"]["counts"]
    columns = st.columns(4)
    columns[0].metric("Score", changes["score"], f"{changes['score_delta']:+}")
    columns[1].metric("Functions added", counts["added"])
    columns[2].metric("Rewritten", counts["modified"])
    columns[3].metric("Removed", counts["removed"])

    for note in changes["highlights"]:
        (st.warning if note["level"] == "warning" else st.info)(note["text"])

    modified = changes["functions"]["modified"]
    if modified:
        frame = pd.DataFrame(modified)[
            ["qualname", "complexity_before", "complexity_after", "complexity_delta",
             "loc_before", "loc_after", "file"]]
        st.dataframe(frame, use_container_width=True, hide_index=True)

    for diff in (changes.get("code") or [])[:10]:
        with st.expander(f"{diff['qualname']} — {diff['kind']} "
                         f"(+{diff['stats']['added']}/-{diff['stats']['removed']})"):
            lines = []
            for row in diff["rows"]:
                if row["type"] == "equal":
                    lines.append("  " + row["left"]["text"])
                elif row["type"] == "replace":
                    lines.append("- " + row["left"]["text"])
                    lines.append("+ " + row["right"]["text"])
                elif row["type"] == "delete":
                    lines.append("- " + row["left"]["text"])
                else:
                    lines.append("+ " + row["right"]["text"])
            st.code("\n".join(lines), language="diff")


def render_source(report: dict) -> None:
    files = (report.get("sources") or {}).get("files") or {}
    if not files:
        st.info("This report does not embed source code.")
        return
    path = st.selectbox("File", sorted(files), format_func=lambda p: p)
    payload = files[path]
    if payload["findings"]:
        st.caption(" · ".join(f"{f['line']}: {f['title']}" for f in payload["findings"][:10]))
    st.code("\n".join(payload["lines"]), language=payload["language"] or "text",
            line_numbers=True)


# --------------------------------------------------------------------------- #
def main() -> None:
    st.set_page_config(page_title="ArchRay Explorer", page_icon="◈", layout="wide")
    args = parse_args()

    st.sidebar.title("ArchRay Explorer")
    folder = st.sidebar.text_input("Reports folder", args.reports)
    reports = load_reports(folder)

    if not reports:
        st.title("ArchRay Explorer")
        st.warning(f"No ArchRay reports found in `{folder}`.")
        st.markdown(
            "Generate one first:\n\n"
            "```bash\n"
            "archray ./my-project --history 400 --format json --out reports/my-project\n"
            "```\n\n"
            "This explorer is for comparing many analyses. For a single project the "
            "self-contained HTML report is usually the better artefact — it needs no "
            "server and can be attached to a build."
        )
        return

    if st.sidebar.button("Reload from disk"):
        load_reports.clear()
        st.rerun()

    st.sidebar.caption(f"{len(reports)} reports loaded")
    selection = st.sidebar.selectbox("Project", list(reports))
    report = reports[selection]

    grade = report["health"]["grade"]
    st.markdown(
        f"## {report.get('repository', {}).get('name', 'project')} "
        f"<span style='color:{GRADE_COLOR.get(grade, '#888')}'>· {grade}</span>",
        unsafe_allow_html=True)

    tabs = st.tabs(["Overview", "Findings", "Structure", "History",
                    "Bindings", "Changes", "Source", "Portfolio"])
    with tabs[0]:
        render_project(report)
    with tabs[1]:
        render_findings(report)
    with tabs[2]:
        render_structure(report)
    with tabs[3]:
        render_history(report)
    with tabs[4]:
        render_bindings(report)
    with tabs[5]:
        render_changes(report)
    with tabs[6]:
        render_source(report)
    with tabs[7]:
        render_overview(reports)


if __name__ == "__main__":
    main()
