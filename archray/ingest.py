"""Ingestion phase: fetch a repository and decide which files to parse."""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

GITHUB_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/(?P<owner>[\w.\-]+)/(?P<repo>[\w.\-]+?)(?:\.git)?/?$"
)

EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", ".idea", ".vscode", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "__pycache__", "node_modules", "venv", ".venv", "env",
    "site-packages", "dist", "build", "target", "out", "bin", "obj",
    "migrations", "vendor", "third_party", ".tox", "htmlcov", "coverage",
    "docs/_build", ".next", ".nuxt", "bower_components",
}

TEST_PATTERNS = (
    re.compile(r"(^|/)tests?(/|$)"),
    re.compile(r"(^|/)test_[^/]+\.py$"),
    re.compile(r"[^/]+_test\.py$"),
    re.compile(r"[^/]+\.(spec|test)\.(ts|js|tsx|jsx)$"),
    re.compile(r"[^/]+\.d\.ts$"),
    re.compile(r"(^|/)[\w.\-]*(test|spec|fuzz|bench)[\w.\-]*/"),
    re.compile(r"[^/]+Test\.java$"),
    re.compile(r"[^/]+Tests?\.cs$"),
    re.compile(r"[^/]+_test\.(c|cc|cpp)$"),
    re.compile(r"(^|/)(unittest|gtest|googletest|catch2)/"),
    re.compile(r"(^|/)conftest\.py$"),
)

LANGUAGE_EXTENSIONS = {
    "python": (".py",),
    "java": (".java",),
    "typescript": (".ts", ".tsx"),
    "csharp": (".cs",),
    "cpp": (".cpp", ".cc", ".cxx", ".hpp", ".hh", ".h"),
    "c": (".c", ".h"),
}
LANGUAGE_LABELS = {
    "python": "Python", "java": "Java", "typescript": "TypeScript",
    "csharp": "C#", "cpp": "C++", "c": "C",
}
# `.h` belongs to both C and C++; whichever implementation files exist decides.
AMBIGUOUS_EXTENSIONS = {".h": ("cpp", "c")}
MIN_FILES_PER_LANGUAGE = 3
MIN_SHARE_PER_LANGUAGE = 0.04

MAX_FILE_BYTES = 800_000


@dataclass
class Repository:
    """A checked-out repository ready to be analysed."""

    root: Path
    name: str
    url: str = ""
    ref: str = ""
    _temporary: bool = False

    def cleanup(self) -> None:
        if self._temporary and self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)

    def __enter__(self) -> "Repository":
        return self

    def __exit__(self, *exc: object) -> None:
        self.cleanup()


def is_github_url(value: str) -> bool:
    return bool(GITHUB_RE.match(value.strip()))


def clone(url: str, depth: int = 1, timeout: int = 300) -> Repository:
    """Shallow-clone a GitHub repository into a temp directory."""
    match = GITHUB_RE.match(url.strip())
    if not match:
        raise ValueError(f"Not a valid GitHub repository URL: {url}")

    owner, repo = match.group("owner"), match.group("repo")
    clone_url = f"https://github.com/{owner}/{repo}.git"
    tmp = Path(tempfile.mkdtemp(prefix="archray-"))
    target = tmp / repo

    cmd = ["git", "clone", "--depth", str(depth), "--single-branch",
           "--quiet", clone_url, str(target)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError(
            f"Clone failed ({clone_url}): {proc.stderr.strip() or 'unknown error'}"
        )

    head = subprocess.run(["git", "-C", str(target), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True)
    return Repository(root=target, name=f"{owner}/{repo}", url=clone_url,
                      ref=head.stdout.strip(), _temporary=True)


def open_source(source: str, depth: int = 1) -> Repository:
    """Accept either a GitHub URL or a local directory path.

    `depth` matters: history analysis needs commits, and a depth-1 clone has
    exactly one.
    """
    if is_github_url(source):
        return clone(source, depth=depth)
    path = Path(source).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"Folder not found: {source}")
    return Repository(root=path, name=path.name)


def _is_excluded_dir(rel_parts: tuple[str, ...]) -> bool:
    return any(part in EXCLUDED_DIRS for part in rel_parts)


def is_test_file(rel_path: str) -> bool:
    return any(p.search(rel_path) for p in TEST_PATTERNS)


def all_source_files(repo: Repository, include_tests: bool = False,
                     exclude_paths: list[str] | None = None) -> dict[str, list[Path]]:
    """Group every analysable file in the repository by extension."""
    by_extension: dict[str, list[Path]] = {}
    known = {ext for extensions in LANGUAGE_EXTENSIONS.values() for ext in extensions}

    for dirpath, dirnames, filenames in os.walk(repo.root):
        rel_dir = Path(dirpath).relative_to(repo.root)
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith(".")]
        if _is_excluded_dir(rel_dir.parts):
            continue
        for filename in filenames:
            extension = os.path.splitext(filename)[1]
            if extension not in known:
                continue
            full = Path(dirpath) / filename
            rel = str(full.relative_to(repo.root)).replace(os.sep, "/")
            if not include_tests and is_test_file(rel):
                continue
            if exclude_paths and any(fnmatch.fnmatch(rel, p) for p in exclude_paths):
                continue
            try:
                if full.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            by_extension.setdefault(extension, []).append(full)
    return by_extension


def plan(repo: Repository, language: str = "auto", include_tests: bool = False,
         exclude_paths: list[str] | None = None) -> dict[str, list[Path]]:
    """Decide which language owns which files.

    Real projects are rarely written in one language: a service with a TypeScript
    front-end and a Java back-end is one system and deserves one report. With
    `language="auto"` every language that carries a meaningful share of the code
    is analysed, and each file is assigned to exactly one of them.
    """
    by_extension = all_source_files(repo, include_tests, exclude_paths)
    if not by_extension:
        return {}

    if language != "auto":
        extensions = LANGUAGE_EXTENSIONS.get(language)
        if not extensions:
            raise ValueError(f"Unsupported language: {language}")
        files = sorted(f for ext in extensions for f in by_extension.get(ext, []))
        return {language: files} if files else {}

    # unambiguous extensions first, so we know which languages are really present
    owners: dict[str, list[Path]] = {}
    for name, extensions in LANGUAGE_EXTENSIONS.items():
        for extension in extensions:
            if extension in AMBIGUOUS_EXTENSIONS:
                continue
            owners.setdefault(name, []).extend(by_extension.get(extension, []))
    owners = {name: files for name, files in owners.items() if files}

    for extension, candidates in AMBIGUOUS_EXTENSIONS.items():
        headers = by_extension.get(extension, [])
        if not headers:
            continue
        winner = next((c for c in candidates if owners.get(c)), candidates[-1])
        owners.setdefault(winner, []).extend(headers)

    total = sum(len(files) for files in owners.values())
    kept = {
        name: sorted(files) for name, files in owners.items()
        if len(files) >= MIN_FILES_PER_LANGUAGE
        or len(files) / total >= MIN_SHARE_PER_LANGUAGE
    }
    if not kept:                                   # tiny repository: keep the largest
        largest = max(owners, key=lambda name: len(owners[name]))
        kept = {largest: sorted(owners[largest])}
    return dict(sorted(kept.items(), key=lambda item: -len(item[1])))


def collect_files(repo: Repository, language: str = "python",
                  include_tests: bool = False,
                  exclude_paths: list[str] | None = None) -> list[Path]:
    """Return the analysable source files of the repository."""
    extensions = LANGUAGE_EXTENSIONS.get(language)
    if not extensions:
        raise ValueError(f"Unsupported language: {language}")

    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(repo.root):
        rel_dir = Path(dirpath).relative_to(repo.root)
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith(".")]
        if _is_excluded_dir(rel_dir.parts):
            continue
        for filename in filenames:
            if not filename.endswith(extensions):
                continue
            full = Path(dirpath) / filename
            rel = str(full.relative_to(repo.root)).replace(os.sep, "/")
            if not include_tests and is_test_file(rel):
                continue
            if exclude_paths and any(fnmatch.fnmatch(rel, pattern)
                                     for pattern in exclude_paths):
                continue
            try:
                if full.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            files.append(full)
    files.sort()
    return files
