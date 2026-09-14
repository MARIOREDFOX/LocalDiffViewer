"""Data models for a whole left-vs-right comparison run."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ChangeStatus(str, Enum):
    ADDED = "added"
    DELETED = "deleted"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"
    RENAMED = "renamed"


@dataclass
class FileChange:
    """One entry in the comparison result: a single file's status."""

    status: ChangeStatus
    rel_path: str  # path used for display / as the tree key
    left_path: Optional[str] = None   # original path on the left, if any
    right_path: Optional[str] = None  # original path on the right, if any
    size_left: Optional[int] = None
    size_right: Optional[int] = None
    hash_left: Optional[str] = None
    hash_right: Optional[str] = None
    is_binary: bool = False
    similarity: Optional[float] = None  # only set for renames


@dataclass
class ComparisonSummary:
    total: int = 0
    added: int = 0
    deleted: int = 0
    modified: int = 0
    unchanged: int = 0
    renamed: int = 0


@dataclass
class ComparisonResult:
    comparison_id: str
    left_label: str
    right_label: str
    summary: ComparisonSummary
    changes: list[FileChange] = field(default_factory=list)
    duration_seconds: float = 0.0
    ignore_patterns: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
