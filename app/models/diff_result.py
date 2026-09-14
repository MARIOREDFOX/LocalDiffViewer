"""Data models describing the result of diffing a single pair of files."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class LineOp(str, Enum):
    EQUAL = "equal"
    ADD = "add"
    DELETE = "delete"
    REPLACE = "replace"
    CONTEXT_SKIP = "context_skip"  # collapsed run of unchanged lines


@dataclass
class DiffRow:
    """One row of a side-by-side diff table.

    A row may have a line on the left, the right, both (equal/replace), or
    neither in the case of a padding row used to keep the two sides aligned
    for pure additions/deletions.
    """

    op: LineOp
    left_no: Optional[int] = None
    left_text: Optional[str] = None
    right_no: Optional[int] = None
    right_text: Optional[str] = None
    skipped_count: int = 0  # used only when op == CONTEXT_SKIP


@dataclass
class FileDiff:
    """Full diff payload for a single file, text or binary."""

    rel_path: str
    is_binary: bool
    identical: bool
    left_size: Optional[int] = None
    right_size: Optional[int] = None
    left_hash: Optional[str] = None
    right_hash: Optional[str] = None
    rows: list[DiffRow] = field(default_factory=list)
    unified: list[str] = field(default_factory=list)
    additions: int = 0
    deletions: int = 0
    truncated: bool = False
    skipped_reason: Optional[str] = None
    left_missing: bool = False
    right_missing: bool = False
