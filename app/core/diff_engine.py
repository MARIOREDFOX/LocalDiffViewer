"""Line-level diff generation for text files.

Built entirely on Python's standard-library ``difflib`` -- no Git involved.
Produces both a unified-diff text form and a side-by-side row structure
that the frontend renders directly (with equal runs collapsible).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from app.models.diff_result import DiffRow, LineOp

CONTEXT_LINES = 3  # lines of context kept around a change before collapsing
_WS_RE = re.compile(r"\s+")


@dataclass
class DiffOptions:
    ignore_whitespace: bool = False
    ignore_blank_lines: bool = False
    ignore_case: bool = False
    collapse_unchanged: bool = True


def _normalize_for_compare(line: str, options: DiffOptions) -> str:
    out = line
    if options.ignore_whitespace:
        out = _WS_RE.sub("", out)
    if options.ignore_case:
        out = out.lower()
    return out


def split_lines(text: str) -> list[str]:
    """Split on \\n keeping content but not the newline, normalizing CRLF."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized == "":
        return []
    lines = normalized.split("\n")
    # A trailing newline produces one trailing empty element after split;
    # drop it so "a\nb\n" -> ["a", "b"] rather than ["a", "b", ""].
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def generate_unified_diff(left_lines: list[str], right_lines: list[str], left_name: str, right_name: str) -> list[str]:
    return list(
        difflib.unified_diff(left_lines, right_lines, fromfile=left_name, tofile=right_name, lineterm="")
    )


def generate_side_by_side(
    left_lines: list[str],
    right_lines: list[str],
    options: DiffOptions | None = None,
) -> tuple[list[DiffRow], int, int]:
    """Build aligned side-by-side rows plus (additions, deletions) counts."""
    options = options or DiffOptions()

    cmp_left = [_normalize_for_compare(l, options) for l in left_lines]
    cmp_right = [_normalize_for_compare(l, options) for l in right_lines]

    if options.ignore_blank_lines:
        left_idx = [i for i, l in enumerate(cmp_left) if l.strip() != ""]
        right_idx = [i for i, l in enumerate(cmp_right) if l.strip() != ""]
        cmp_left_f = [cmp_left[i] for i in left_idx]
        cmp_right_f = [cmp_right[i] for i in right_idx]
    else:
        left_idx = list(range(len(cmp_left)))
        right_idx = list(range(len(cmp_right)))
        cmp_left_f = cmp_left
        cmp_right_f = cmp_right

    # autojunk=True (the difflib default) is important here: it treats
    # lines that appear very frequently (>1% of a large file) as "popular"
    # and skips using them as synchronization anchors. Without it, files
    # with many repeated/near-identical lines (common in generated code,
    # data files, or pathological test fixtures) can degrade to near-
    # quadratic behavior and hang the request. This costs a small amount
    # of diff "prettiness" on such files in exchange for bounded latency.
    matcher = difflib.SequenceMatcher(a=cmp_left_f, b=cmp_right_f, autojunk=True)
    opcodes = matcher.get_opcodes()

    rows: list[DiffRow] = []
    additions = 0
    deletions = 0

    equal_run: list[DiffRow] = []

    def flush_equal_run():
        nonlocal equal_run
        if not equal_run:
            return
        if options.collapse_unchanged and len(equal_run) > CONTEXT_LINES * 2:
            rows.extend(equal_run[:CONTEXT_LINES])
            skipped = len(equal_run) - CONTEXT_LINES * 2
            rows.append(DiffRow(op=LineOp.CONTEXT_SKIP, skipped_count=skipped))
            rows.extend(equal_run[-CONTEXT_LINES:])
        else:
            rows.extend(equal_run)
        equal_run = []

    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            for k in range(i2 - i1):
                li = left_idx[i1 + k]
                ri = right_idx[j1 + k]
                equal_run.append(
                    DiffRow(op=LineOp.EQUAL, left_no=li + 1, left_text=left_lines[li], right_no=ri + 1, right_text=right_lines[ri])
                )
            continue

        flush_equal_run()

        left_span = [left_idx[k] for k in range(i1, i2)]
        right_span = [right_idx[k] for k in range(j1, j2)]

        if tag == "replace":
            n = max(len(left_span), len(right_span))
            for k in range(n):
                li = left_span[k] if k < len(left_span) else None
                ri = right_span[k] if k < len(right_span) else None
                if li is not None:
                    deletions += 1
                if ri is not None:
                    additions += 1
                rows.append(
                    DiffRow(
                        op=LineOp.REPLACE,
                        left_no=(li + 1) if li is not None else None,
                        left_text=left_lines[li] if li is not None else None,
                        right_no=(ri + 1) if ri is not None else None,
                        right_text=right_lines[ri] if ri is not None else None,
                    )
                )
        elif tag == "delete":
            for li in left_span:
                deletions += 1
                rows.append(DiffRow(op=LineOp.DELETE, left_no=li + 1, left_text=left_lines[li]))
        elif tag == "insert":
            for ri in right_span:
                additions += 1
                rows.append(DiffRow(op=LineOp.ADD, right_no=ri + 1, right_text=right_lines[ri]))

    flush_equal_run()
    return rows, additions, deletions
