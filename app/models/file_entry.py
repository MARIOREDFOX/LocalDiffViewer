"""Data model for a single file discovered while scanning a folder or ZIP."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FileEntry:
    """A normalized, filesystem-agnostic representation of one file.

    ``rel_path`` always uses forward slashes and is relative to the root of
    whichever source (folder or extracted ZIP) it was scanned from. Two
    entries from different sources are considered "the same file" when their
    ``rel_path`` values are equal.
    """

    rel_path: str
    abs_path: str
    size: int
    sha256: str
    is_binary: bool
    is_dir: bool = False

    @property
    def name(self) -> str:
        return self.rel_path.rsplit("/", 1)[-1]

    @property
    def extension(self) -> str:
        name = self.name
        if "." in name:
            return name.rsplit(".", 1)[-1].lower()
        return ""
