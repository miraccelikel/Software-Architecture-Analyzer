"""Command line entry point: `archray <repo|path>`."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .changes import compare as compare_structure
from .changes import materialise
from .compare import compare as compare_findings
from .config import Thresholds
from .engine import VERSION, analyze_source
from .environment import detect, report as environment_report
from .report import (write_changes, write_html, write_json, write_pr_comment,
                     write_sarif, write_tour)

COLORS = {"critical": "\033[91m", "major": "\033[93m", "minor": "\033[96m",
          "info": "\033[90m", "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
          "good": "\033[92m", "warning": "\033[93m"}
GRADE_COLOR = {"A": "\033[92m", "B": "\033[92m", "C": "\033[93m",
               "D": "\033[91m", "F": "\033[91m"}
LANGUAGES = ["auto", "python", "java", "typescript", "csharp", "cpp", "c"]


def _ensure_utf8_streams() -> None:
    """Make stdout/stderr UTF-8 regardless of the console's code page.

    A plain Windows console defaults to a legacy code page — cp1252, cp437 —
    that cannot encode the tick marks, box-drawing separators and arrows this
    CLI prints, and Python raises `UnicodeEncodeError` the moment one is
    written. Reconfiguring the streams here fixes it for every command that
    goes through `main()`, without requiring `PYTHONIOENCODING=utf-8` or
    `chcp 65001` to be set beforehand. It is a no-op on platforms that are
    already UTF-8 (Linux, macOS, modern Windows Terminal).
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def _paint(text: str, key: str, enabled: bool) -> str:
    return f"{COLORS.get(key, '')}{text}{COLORS['reset']}" if enabled else text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="archray",
        description="Architecture report for a GitHub repository or a local folder.",
    )
    parser.add_argument("source", nargs="?",
                        help="GitHub repository URL or local folder path")
    parser.add_argument("--doctor", action="store_true",
                        help="Check the toolchain and print how to complete it")
    parser.add_argument("--lang", default="auto", choices=LANGUAGES,
                        help="Language to analyse; 'auto' detects and analyses all of them")
    parser.add_argument("--out", default="archray-report",
                        help="Prefix for the output files (default: archray-report)")
    parser.add_argument("--format", default="json,html",
                        help="Comma-separated outputs: json, html, md, sarif, pr, changes")
    parser.add_argument("--config", default=None,
                        help="A .toml/.json file with thresholds and ignore rules")
    parser.add_argument("--include-tests", action="store_true",
                        help="Analyse test files as well")
    parser.add_argument("--history", type=int, nargs="?", const=800, default=0,
                        metavar="COMMITS",
                        help="Also read the git log (default: last 800 commits)")
    parser.add_argument("--changes", default=None, metavar="REVISION",
                        help="Structural diff against a git revision, e.g. HEAD or main")
    parser.add_argument("--compare", default=None, metavar="OLD.json",
                        help="Compare findings with an earlier report")
    parser.add_argument("--fail-on-new", action="store_true",
                        help="With --compare/--changes: exit 1 if new findings appeared")
    parser.add_argument("--fail-under", type=float, default=None,
                        help="Exit 1 when the health score is below this value (for CI)")
    parser.add_argument("--top", type=int, default=5, help="How many debts to print")
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("--version", action="version", version=f"ArchRay {VERSION}")
    return parser


# --------------------------------------------------------------------------- #
def print_summary(report: dict, top: int, color: bool) -> None:
    health = report["health"]
    summary = report["summary"]
    repository = report.get("repository", {})
    grade = health["grade"]
    grade_text = f" {grade} " if not color else f"{GRADE_COLOR[grade]}\033[1m {grade} \033[0m"

    print()
    print(_paint(f"  {repository.get('name', 'project')}", "bold", color),
          _paint(f"({repository.get('ref') or 'local'})", "dim", color))
    print("  " + "-" * 62)
    print(f"  Health score   {health['score']}/100   grade:{grade_text}  {health['verdict']}")
    for dimension in health["dimensions"]:
        filled = int(dimension["score"] / 5)
        bar = "#" * filled + "." * (20 - filled)
        print(f"    {dimension['label']:<22} {bar} {dimension['score']:>3}")
    print("  " + "-" * 62)

    languages = summary.get("languages") or []
    if len(languages) > 1:
        breakdown = " . ".join(f"{item['language']} {item['sloc']}" for item in languages)
        print(f"  Languages: {breakdown}")
    print(f"  {summary['modules']} modules . {summary['classes']} classes . "
          f"{summary['functions']} functions . {summary['sloc']} lines of code")

    severities = summary["by_severity"]
    print(f"  {summary['findings']} findings -> "
          f"{_paint(str(severities.get('critical', 0)) + ' critical', 'critical', color)}, "
          f"{_paint(str(severities.get('major', 0)) + ' major', 'major', color)}, "
          f"{_paint(str(severities.get('minor', 0)) + ' minor', 'minor', color)}")
    print(f"  {summary['patterns']} design patterns . {summary['cycles']} circular dependencies")

    unsupported = repository.get("unsupported") or []
    if unsupported:
        for item in unsupported:
            print(_paint(f"  ! {item['language']} skipped ({item['files']} files): "
                         f"grammar not installed", "warning", color))
        print(_paint("    run `archray --doctor` for the exact install command", "dim", color))

    if report["top_debt"]:
        print()
        print(_paint("  Most urgent technical debt", "bold", color))
        for item in report["top_debt"][:top]:
            tag = _paint(f"[{item['severity']}]", item["severity"], color)
            print(f"   {item['rank']}. {tag} {item['title']} -- {item['symbol'] or item['file']}")
            print(_paint(f"      {item['file']}:{item['line']}", "dim", color))

    evolution = report.get("history")
    if evolution:
        print()
        print(_paint(f"  History  {evolution['commits_scanned']} commits . "
                     f"{evolution['authors']} authors", "bold", color))
        for spot in evolution["hotspots"][:3]:
            print(f"   . {spot['file']} -- {spot['revisions']} changes, "
                  f"complexity {spot['complexity']}, risk {spot['risk']}")
        for link in evolution["coupling"][:2]:
            print(f"   . changes together: {link['files'][0]} <-> {link['files'][1]} "
                  f"({int(link['degree'] * 100)}%)")

    print_structural_changes(report, color)

    diff = report.get("comparison")
    if diff:
        print()
        arrow = "^" if diff["score_delta"] > 0 else ("v" if diff["score_delta"] < 0 else "=")
        print(_paint(f"  Against the previous report  {arrow} {diff['score_delta']:+} points",
                     "bold", color))
        print(f"   {diff['verdict']}")

    patterns = report["patterns"][:6]
    if patterns:
        print()
        print(_paint("  Detected patterns", "bold", color))
        for match in patterns:
            print(f"   . {match['pattern']:<20} {int(match['confidence'] * 100):>3}%  "
                  f"{', '.join(match['participants'][:3])}")
    print()


def print_structural_changes(report: dict, color: bool) -> None:
    changes = report.get("changes")
    if not changes:
        return
    print()
    print(_paint(f"  What changed since {changes['revision']}", "bold", color))
    print(f"   {changes['headline']}")
    for note in changes["highlights"][:8]:
        marker = "!" if note["level"] == "warning" else "."
        print(f"   {_paint(marker, 'warning' if note['level'] == 'warning' else 'dim', color)} "
              f"{note['text']}")
    counts = changes["functions"]["counts"]
    print(_paint(f"      functions +{counts['added']} ~{counts['modified']} "
                 f"-{counts['removed']}", "dim", color))


# --------------------------------------------------------------------------- #
def run_structural_diff(args, report: dict, thresholds: Thresholds) -> dict | None:
    """Analyse a git revision of the same source and diff the two structures."""
    root = Path(args.source).expanduser().resolve()
    if not root.is_dir():
        print("--changes only works on a local checkout with git history.", file=sys.stderr)
        return None

    snapshot = None
    try:
        snapshot = materialise(root, args.changes)
        baseline = analyze_source(str(snapshot), language=args.lang,
                                  thresholds=thresholds, include_tests=args.include_tests)
        # the snapshot has to outlive the comparison: the code diffs are read
        # from both trees while they are still on disk
        return compare_structure(baseline, report, args.changes, snapshot, root)
    except RuntimeError as exc:
        print(f"Structural diff skipped: {exc}", file=sys.stderr)
        return None
    finally:
        if snapshot is not None:
            shutil.rmtree(snapshot, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_streams()

    parser = build_parser()
    args = parser.parse_args(argv)
    color = sys.stdout.isatty() and not args.no_color

    if args.doctor:
        print(environment_report(use_color=color))
        return 0
    if not args.source:
        parser.error("a repository URL or folder path is required (or use --doctor)")

    try:
        thresholds = Thresholds.load(args.config) if args.config else Thresholds()
        report = analyze_source(args.source, language=args.lang, thresholds=thresholds,
                                include_tests=args.include_tests,
                                history_commits=args.history)
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"Analysis failed: {exc}", file=sys.stderr)
        return 2

    if args.compare:
        try:
            previous = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Could not read the comparison report: {exc}", file=sys.stderr)
            return 2
        report["comparison"] = compare_findings(previous, report)

    if args.changes:
        changes = run_structural_diff(args, report, thresholds)
        if changes:
            report["changes"] = changes
            report.setdefault("comparison", changes["findings"])

    formats = {f.strip().lower() for f in args.format.split(",") if f.strip()}
    outputs: list[Path] = []
    if "json" in formats:
        outputs.append(write_json(report, Path(f"{args.out}.json")))
    if "html" in formats:
        outputs.append(write_html(report, Path(f"{args.out}.html")))
    if "sarif" in formats:
        outputs.append(write_sarif(report, Path(f"{args.out}.sarif")))
    if "pr" in formats:
        outputs.append(write_pr_comment(report, Path(f"{args.out}-pr.md")))
    if "md" in formats or "tour" in formats:
        outputs.append(write_tour(report, Path(f"{args.out}-tour.md")))
    if "changes" in formats and report.get("changes"):
        outputs.append(write_changes(report, Path(f"{args.out}-changes.md")))

    print_summary(report, args.top, color)
    for path in outputs:
        print(f"  -> {path}")
    print()

    diff = report.get("comparison")
    if args.fail_on_new and diff and diff["new_count"]:
        print(f"{diff['new_count']} new findings.", file=sys.stderr)
        return 1
    if args.fail_under is not None and report["health"]["score"] < args.fail_under:
        print(f"Score below the threshold ({report['health']['score']} < {args.fail_under}).",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
