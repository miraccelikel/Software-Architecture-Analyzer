"""What the source code cannot tell you: how the code actually evolves.

A static snapshot says a file is complex. It cannot say whether anyone ever
touches it. Complex code that nobody edits is not a problem worth paying for;
complex code that changes every week is where the money goes. This module reads
`git log` and adds the missing dimension:

* **change frequency** — how often each file is revised,
* **change coupling** — files that keep being committed together even though no
  import connects them, which is the coupling a dependency graph cannot see,
* **knowledge islands** — files that only one person has ever touched.
"""

from __future__ import annotations

import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .models import Finding

SEPARATOR = "\x1f"
COMMIT_MARK = "\x1e"
MERGE_LIMIT = 60          # a commit touching more files than this couples nothing meaningfully
MIN_SHARED_COMMITS = 4
MIN_COUPLING = 0.45
MIN_REVISIONS_FOR_COUPLING = 5


@dataclass
class FileHistory:
    path: str
    revisions: int = 0
    authors: Counter = field(default_factory=Counter)
    added: int = 0
    deleted: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0

    @property
    def author_count(self) -> int:
        return len(self.authors)

    @property
    def main_author_share(self) -> float:
        if not self.revisions:
            return 0.0
        return self.authors.most_common(1)[0][1] / sum(self.authors.values())

    def to_dict(self) -> dict:
        return {
            "file": self.path,
            "revisions": self.revisions,
            "authors": self.author_count,
            "main_author_share": round(self.main_author_share, 2),
            "added": self.added,
            "deleted": self.deleted,
            "last_change": datetime.fromtimestamp(self.last_seen, timezone.utc)
                            .strftime("%Y-%m-%d") if self.last_seen else "",
        }


def available(root: Path) -> bool:
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
                            capture_output=True, text=True)
    return result.returncode == 0 and result.stdout.strip() == "true"


def _run_log(root: Path, max_commits: int) -> str:
    command = [
        "git", "-C", str(root), "log", f"--max-count={max_commits}",
        "--no-merges", "--numstat", "--date=unix",
        f"--format={COMMIT_MARK}%H{SEPARATOR}%at{SEPARATOR}%an",
    ]
    result = subprocess.run(command, capture_output=True, text=True, errors="replace")
    return result.stdout if result.returncode == 0 else ""


def collect(root: Path, tracked: set[str], max_commits: int = 800) -> dict:
    """Read the log and reduce it to per-file and per-pair statistics."""
    raw = _run_log(root, max_commits)
    if not raw.strip():
        return {}

    files: dict[str, FileHistory] = {}
    pairs: Counter[tuple[str, str]] = Counter()
    commits = 0

    for block in raw.split(COMMIT_MARK):
        if not block.strip():
            continue
        header, _, body = block.partition("\n")
        parts = header.split(SEPARATOR)
        if len(parts) < 3:
            continue
        _sha, timestamp, author = parts[0], float(parts[1] or 0), parts[2]
        commits += 1

        touched: list[str] = []
        for line in body.splitlines():
            columns = line.split("\t")
            if len(columns) != 3:
                continue
            added, deleted, path = columns
            path = _normalise_rename(path)
            if path not in tracked:
                continue
            entry = files.setdefault(path, FileHistory(path))
            entry.revisions += 1
            entry.authors[author] += 1
            entry.added += int(added) if added.isdigit() else 0
            entry.deleted += int(deleted) if deleted.isdigit() else 0
            entry.last_seen = max(entry.last_seen, timestamp)
            entry.first_seen = min(entry.first_seen or timestamp, timestamp)
            touched.append(path)

        # a sweeping commit couples everything with everything; it means nothing
        if 1 < len(touched) <= MERGE_LIMIT:
            unique = sorted(set(touched))
            for i, left in enumerate(unique):
                for right in unique[i + 1:]:
                    pairs[(left, right)] += 1

    if not files:
        return {}

    return {
        "commits_scanned": commits,
        "files": {path: entry for path, entry in files.items()},
        "pairs": pairs,
    }


def _normalise_rename(path: str) -> str:
    """`src/{old => new}/file.py` — keep the current name."""
    if "=>" not in path:
        return path.strip()
    if "{" in path and "}" in path:
        head, _, rest = path.partition("{")
        middle, _, tail = rest.partition("}")
        return (head + middle.split("=>")[-1].strip() + tail).replace("//", "/").strip()
    return path.split("=>")[-1].strip().strip("}").strip()


# --------------------------------------------------------------------------- #
def summarise(data: dict, module_of: dict[str, str],
              complexity_of: dict[str, int]) -> dict:
    """Turn raw counts into the numbers a reader can act on."""
    if not data:
        return {}

    files: dict[str, FileHistory] = data["files"]
    ranked = sorted(files.values(), key=lambda f: -f.revisions)
    max_revisions = ranked[0].revisions if ranked else 1

    hotspots = []
    for entry in ranked[:40]:
        complexity = complexity_of.get(entry.path, 0)
        churn = entry.revisions / max_revisions
        hotspots.append({
            **entry.to_dict(),
            "module": module_of.get(entry.path, ""),
            "complexity": complexity,
            # the core insight: complexity multiplied by how often it changes
            "risk": round(churn * complexity, 1),
        })
    hotspots.sort(key=lambda h: -h["risk"])

    coupling = []
    for (left, right), shared in data["pairs"].most_common(400):
        left_revisions = files[left].revisions if left in files else 0
        right_revisions = files[right].revisions if right in files else 0
        smaller = min(left_revisions, right_revisions)
        if smaller < MIN_REVISIONS_FOR_COUPLING or shared < MIN_SHARED_COMMITS:
            continue
        degree = shared / smaller
        if degree < MIN_COUPLING:
            continue
        coupling.append({
            "files": [left, right], "shared_commits": shared,
            "degree": round(degree, 2),
            "same_module": module_of.get(left) == module_of.get(right),
        })
    coupling.sort(key=lambda c: (-c["degree"], -c["shared_commits"]))

    islands = [entry.to_dict() for entry in ranked
               if entry.revisions >= 5 and entry.main_author_share >= 0.9]

    return {
        "commits_scanned": data["commits_scanned"],
        "files_tracked": len(files),
        "authors": len({author for entry in files.values() for author in entry.authors}),
        "hotspots": hotspots[:15],
        "coupling": coupling[:15],
        "knowledge_islands": islands[:10],
        "stale_but_complex": _stale(ranked, complexity_of)[:8],
    }


def _stale(ranked: list[FileHistory], complexity_of: dict[str, int]) -> list[dict]:
    """Complex code that nobody has touched — expensive to read, cheap to leave alone."""
    out = []
    for entry in ranked:
        complexity = complexity_of.get(entry.path, 0)
        if entry.revisions <= 2 and complexity >= 40:
            out.append({**entry.to_dict(), "complexity": complexity})
    out.sort(key=lambda item: -item["complexity"])
    return out


def findings(summary: dict, module_of: dict[str, str]) -> list[Finding]:
    """The two history-driven rules worth interrupting someone for."""
    if not summary:
        return []

    results: list[Finding] = []
    for spot in summary["hotspots"][:5]:
        if spot["risk"] < 8 or spot["complexity"] < 25:
            continue
        results.append(Finding(
            kind="history", rule="volatile_complex_file", severity="major",
            title="Complex file that changes often",
            message=(f"This file changed {spot['revisions']} times in the scanned history "
                     f"and carries a total complexity of {spot['complexity']}. Complexity "
                     f"alone is not the problem; the cost is in complex code that people "
                     f"keep touching. Spend the refactoring budget here first "
                     f"({spot['authors']} different authors have edited it)."),
            file=spot["file"], line=1, symbol=spot["module"] or spot["file"],
            metrics={"revisions": spot["revisions"], "complexity": spot["complexity"],
                     "risk": spot["risk"], "authors": spot["authors"]},
        ))

    for link in summary["coupling"][:5]:
        if link["same_module"] or link["degree"] < 0.6:
            continue
        left, right = link["files"]
        results.append(Finding(
            kind="history", rule="change_coupling", severity="minor",
            title="Hidden dependency (change coupling)",
            message=(f"`{left}` and `{right}` changed together in "
                     f"{int(link['degree'] * 100)}% of commits "
                     f"({link['shared_commits']} shared commits) — yet no import connects "
                     f"them. This is coupling the dependency graph cannot see: either one "
                     f"concept was copied into two places, or the contract between them "
                     f"lives in people's heads rather than in the code."),
            file=left, line=1, symbol=module_of.get(left, left),
            metrics={"with": right, "degree": link["degree"],
                     "shared_commits": link["shared_commits"]},
        ))
    return results
