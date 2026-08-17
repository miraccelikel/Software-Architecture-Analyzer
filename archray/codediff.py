"""Line and word level diffs for the functions that changed.

The structural report says *that* a function was rewritten and by how much its
complexity moved. This module produces the thing a reviewer actually reads next:
the two versions side by side, with the changed words inside a changed line
marked, the way a diff viewer in an IDE presents them.

Sizes are capped deliberately. A report that embeds every line of a large
refactor becomes unopenable, and nobody reads a five-hundred-line diff in a
summary anyway — that is what the editor is for.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path

MAX_FUNCTION_LINES = 240
MAX_DIFFS = 30
MAX_TOTAL_LINES = 1800
TOKEN = re.compile(r"\s+|\w+|.")


def read_range(root: Path, relative: str, start: int, end: int) -> list[str]:
    """Read an inclusive 1-based line range, tolerating a missing file."""
    path = root / relative
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    start = max(start, 1)
    end = min(max(end, start), len(lines))
    return lines[start - 1:end]


def _segments(before: str, after: str) -> tuple[list[list], list[list]]:
    """Split two lines into [changed, text] runs so the edit itself stands out."""
    left_tokens = TOKEN.findall(before)
    right_tokens = TOKEN.findall(after)
    matcher = SequenceMatcher(None, left_tokens, right_tokens, autojunk=False)

    left: list[list] = []
    right: list[list] = []

    def push(target: list[list], changed: int, text: str) -> None:
        if not text:
            return
        if target and target[-1][0] == changed:
            target[-1][1] += text
        else:
            target.append([changed, text])

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        left_text = "".join(left_tokens[i1:i2])
        right_text = "".join(right_tokens[j1:j2])
        if tag == "equal":
            push(left, 0, left_text)
            push(right, 0, right_text)
        else:
            push(left, 1, left_text)
            push(right, 1, right_text)
    return left, right


def _row(kind: str, left_no: int | None, left_text: str | None,
         right_no: int | None, right_text: str | None,
         left_segments=None, right_segments=None) -> dict:
    row: dict = {"type": kind}
    if left_text is not None:
        row["left"] = {"no": left_no, "text": left_text}
        if left_segments:
            row["left"]["segments"] = left_segments
    if right_text is not None:
        row["right"] = {"no": right_no, "text": right_text}
        if right_segments:
            row["right"]["segments"] = right_segments
    return row


def align(old_lines: list[str], new_lines: list[str],
          old_start: int = 1, new_start: int = 1) -> tuple[list[dict], dict]:
    """Pair the two versions line by line, the way a side-by-side view needs."""
    matcher = SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    rows: list[dict] = []
    added = removed = 0

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                rows.append(_row("equal", old_start + i1 + offset, old_lines[i1 + offset],
                                 new_start + j1 + offset, new_lines[j1 + offset]))
            continue

        if tag == "replace":
            pairs = max(i2 - i1, j2 - j1)
            for offset in range(pairs):
                left_index = i1 + offset
                right_index = j1 + offset
                has_left = left_index < i2
                has_right = right_index < j2
                if has_left and has_right:
                    left_segments, right_segments = _segments(old_lines[left_index],
                                                              new_lines[right_index])
                    rows.append(_row("replace",
                                     old_start + left_index, old_lines[left_index],
                                     new_start + right_index, new_lines[right_index],
                                     left_segments, right_segments))
                    added += 1
                    removed += 1
                elif has_left:
                    rows.append(_row("delete", old_start + left_index,
                                     old_lines[left_index], None, None))
                    removed += 1
                else:
                    rows.append(_row("insert", None, None, new_start + right_index,
                                     new_lines[right_index]))
                    added += 1
            continue

        if tag == "delete":
            for offset in range(i1, i2):
                rows.append(_row("delete", old_start + offset, old_lines[offset], None, None))
                removed += 1
        elif tag == "insert":
            for offset in range(j1, j2):
                rows.append(_row("insert", None, None, new_start + offset, new_lines[offset]))
                added += 1

    return rows, {"added": added, "removed": removed}


def _dedent(*blocks: list[str]) -> list[list[str]]:
    """Strip the indentation the two versions share, so the diff reads flush left."""
    meaningful = [line for block in blocks for line in block if line.strip()]
    if not meaningful:
        return [list(block) for block in blocks]
    indent = min(len(line) - len(line.lstrip()) for line in meaningful)
    return [[line[indent:] if line.strip() else "" for line in block] for block in blocks]


def _truncate(lines: list[str]) -> tuple[list[str], bool]:
    if len(lines) <= MAX_FUNCTION_LINES:
        return lines, False
    return lines[:MAX_FUNCTION_LINES], True


def for_functions(changes: dict, old_root: Path | None, new_root: Path | None,
                  language_of: dict[str, str] | None = None) -> list[dict]:
    """Build a diff per changed function, most interesting first."""
    if old_root is None or new_root is None:
        return []

    language_of = language_of or {}
    candidates: list[tuple[int, str, dict]] = []
    for item in changes["functions"]["modified"]:
        weight = 1000 + abs(item.get("complexity_delta", 0)) * 10
        candidates.append((weight, "modified", item))
    for item in changes["functions"]["removed"]:
        candidates.append((500 + item.get("complexity", 0), "removed", item))
    for item in changes["functions"]["added"]:
        candidates.append((400 + item.get("complexity", 0), "added", item))
    candidates.sort(key=lambda entry: -entry[0])

    diffs: list[dict] = []
    budget = MAX_TOTAL_LINES
    for _weight, kind, item in candidates:
        if len(diffs) >= MAX_DIFFS or budget <= 0:
            break

        if kind == "modified":
            old_lines = read_range(old_root, item["file"],
                                   item.get("line_before") or item["line"],
                                   (item.get("line_before") or item["line"])
                                   + item["loc_before"] - 1)
            new_lines = read_range(new_root, item["file"], item["line"],
                                   item["line"] + item["loc_after"] - 1)
        elif kind == "removed":
            old_lines = read_range(old_root, item["file"], item["line"],
                                   item["line"] + item["loc"] - 1)
            new_lines = []
        else:
            old_lines = []
            new_lines = read_range(new_root, item["file"], item["line"],
                                   item["line"] + item["loc"] - 1)

        if not old_lines and not new_lines:
            continue

        old_lines, old_cut = _truncate(old_lines)
        new_lines, new_cut = _truncate(new_lines)
        old_lines, new_lines = _dedent(old_lines, new_lines)

        rows, stats = align(
            old_lines, new_lines,
            (item.get("line_before") or item.get("line", 1)) if kind != "added" else 1,
            item.get("line", 1) if kind != "removed" else 1,
        )
        budget -= len(rows)

        diffs.append({
            "qualname": item["qualname"],
            "name": item.get("name") or item["qualname"].rsplit(".", 1)[-1],
            "kind": kind,
            "file": item["file"],
            "language": language_of.get(item["file"].rsplit(".", 1)[-1], ""),
            "complexity_before": item.get("complexity_before", item.get("complexity")),
            "complexity_after": item.get("complexity_after", item.get("complexity")),
            "stats": stats,
            "truncated": old_cut or new_cut,
            "rows": rows,
        })
    return diffs


def to_unified(diff: dict, context: int = 3) -> str:
    """A `diff`-fenced block for the Markdown review sheet."""
    lines: list[str] = []
    rows = diff["rows"]
    keep = [index for index, row in enumerate(rows) if row["type"] != "equal"]
    if not keep:
        return ""
    visible = set()
    for index in keep:
        visible.update(range(max(index - context, 0), min(index + context + 1, len(rows))))

    previous = -1
    for index in sorted(visible):
        if previous >= 0 and index > previous + 1:
            lines.append("@@ …")
        row = rows[index]
        if row["type"] == "equal":
            lines.append("  " + row["left"]["text"])
        elif row["type"] == "replace":
            lines.append("- " + row["left"]["text"])
            lines.append("+ " + row["right"]["text"])
        elif row["type"] == "delete":
            lines.append("- " + row["left"]["text"])
        else:
            lines.append("+ " + row["right"]["text"])
        previous = index
    return "\n".join(lines)
