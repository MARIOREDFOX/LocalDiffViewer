"""Builds a single-file `FileDiff` on demand.

This is deliberately separate from `comparator.py`: the comparator only
ever computes cheap metadata (hashes, sizes, status) for the whole tree.
Actually generating line-by-line diff content is comparatively expensive,
so it happens here, lazily, only for the one file the user is currently
looking at (or, for HTML export, for the bounded set the export step asks
for).
"""

from __future__ import annotations

from app.core.diff_engine import DiffOptions, generate_side_by_side, generate_unified_diff, split_lines
from app.models.comparison import ChangeStatus, FileChange
from app.models.diff_result import DiffRow, FileDiff, LineOp
from app.models.file_entry import FileEntry

# Above this combined size (bytes), we don't auto-generate a line diff --
# the UI shows a warning and offers a "diff anyway" action instead.
LARGE_DIFF_WARN_BYTES = 3 * 1024 * 1024
MAX_READ_BYTES = 20 * 1024 * 1024  # hard safety cap even when forced

# Even when the user explicitly forces a diff, cap the number of lines fed
# into difflib. This is a hard latency backstop independent of the
# autojunk optimization: it guarantees a single request can't pin the
# event loop indefinitely regardless of file content.
MAX_DIFF_LINES = 60_000


def _read_text(entry: FileEntry) -> str:
    with open(entry.abs_path, "rb") as fh:
        raw = fh.read(MAX_READ_BYTES)
    return raw.decode("utf-8", errors="replace")


def build_file_diff(
    change: FileChange,
    left_manifest: dict[str, FileEntry],
    right_manifest: dict[str, FileEntry],
    options: DiffOptions | None = None,
    force: bool = False,
) -> FileDiff:
    options = options or DiffOptions()

    left_entry = left_manifest.get(change.left_path) if change.left_path else None
    right_entry = right_manifest.get(change.right_path) if change.right_path else None

    is_binary = change.is_binary
    identical = change.status in (ChangeStatus.UNCHANGED,) or (
        left_entry is not None and right_entry is not None and left_entry.sha256 == right_entry.sha256
    )

    diff = FileDiff(
        rel_path=change.rel_path,
        is_binary=is_binary,
        identical=identical,
        left_size=left_entry.size if left_entry else None,
        right_size=right_entry.size if right_entry else None,
        left_hash=left_entry.sha256 if left_entry else None,
        right_hash=right_entry.sha256 if right_entry else None,
        left_missing=left_entry is None,
        right_missing=right_entry is None,
    )

    if is_binary:
        return diff  # binary: metadata only, no line diff

    combined_size = (left_entry.size if left_entry else 0) + (right_entry.size if right_entry else 0)
    if combined_size > LARGE_DIFF_WARN_BYTES and not force:
        diff.truncated = True
        diff.skipped_reason = (
            f"File pair is large ({combined_size:,} bytes combined). "
            "Diff generation was skipped to keep the app responsive. "
            "Request again with force=true to diff anyway."
        )
        return diff

    left_text = _read_text(left_entry) if left_entry else ""
    right_text = _read_text(right_entry) if right_entry else ""
    left_lines = split_lines(left_text)
    right_lines = split_lines(right_text)

    if len(left_lines) + len(right_lines) > MAX_DIFF_LINES:
        diff.truncated = True
        diff.skipped_reason = (
            f"File pair has too many lines to diff safely "
            f"({len(left_lines) + len(right_lines):,} combined, limit {MAX_DIFF_LINES:,}). "
            "Try viewing the files individually instead."
        )
        return diff

    rows, additions, deletions = generate_side_by_side(left_lines, right_lines, options)
    diff.rows = rows
    diff.additions = additions
    diff.deletions = deletions
    diff.unified = generate_unified_diff(
        left_lines, right_lines, change.left_path or "(none)", change.right_path or "(none)"
    )
    return diff
