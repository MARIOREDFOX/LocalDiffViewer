"""Recursive filesystem scanning into a normalized manifest of FileEntry.

A "source" (one side of the comparison) is always resolved down to a plain
directory on disk before scanning -- ZIPs are extracted first by the caller
(see ``app.core.comparator``). This module only deals with plain folders,
which keeps it simple and unit-testable on its own.
"""

from __future__ import annotations

import os
from typing import Optional

from app.core.file_detector import is_text_path, read_sample
from app.core.hashing import hash_file
from app.core.ignore_rules import IgnoreRules
from app.models.file_entry import FileEntry

# Files larger than this are still hashed and listed, but are flagged so the
# UI/diff layer can warn the user and offer to skip generating a line diff.
LARGE_FILE_WARN_BYTES = 5 * 1024 * 1024  # 5 MiB


def _to_posix(rel: str) -> str:
    return rel.replace(os.sep, "/")


def scan_folder(
    root: str,
    ignore_rules: Optional[IgnoreRules] = None,
) -> dict[str, FileEntry]:
    """Walk ``root`` recursively and return a mapping of rel_path -> FileEntry.

    Empty directories are recorded too (as FileEntry with is_dir=True) so
    that folder structure is preserved even when a directory has no files
    of its own after ignore rules are applied.
    """
    ignore_rules = ignore_rules or IgnoreRules()
    manifest: dict[str, FileEntry] = {}
    root = os.path.abspath(root)

    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = _to_posix(os.path.relpath(dirpath, root))
        if rel_dir == ".":
            rel_dir = ""

        # Prune ignored directories in-place so os.walk doesn't descend
        # into them at all (important for perf on things like
        # node_modules/.git).
        kept = []
        for d in dirnames:
            rel_d = f"{rel_dir}/{d}" if rel_dir else d
            if ignore_rules.is_ignored(rel_d, is_dir=True):
                continue
            kept.append(d)
        dirnames[:] = kept

        if rel_dir and not filenames and not dirnames:
            # Empty directory (after pruning) -- still record it.
            if not ignore_rules.is_ignored(rel_dir, is_dir=True):
                manifest[rel_dir] = FileEntry(
                    rel_path=rel_dir,
                    abs_path=dirpath,
                    size=0,
                    sha256="",
                    is_binary=False,
                    is_dir=True,
                )

        for name in filenames:
            rel_path = f"{rel_dir}/{name}" if rel_dir else name
            if ignore_rules.is_ignored(rel_path, is_dir=False):
                continue

            abs_path = os.path.join(dirpath, name)
            try:
                size = os.path.getsize(abs_path)
                digest = hash_file(abs_path)
                sample = read_sample(abs_path)
                is_bin = not is_text_path(rel_path, sample)
            except OSError:
                # Unreadable file (broken symlink, permissions, etc.) --
                # skip it rather than crash the whole scan.
                continue

            manifest[rel_path] = FileEntry(
                rel_path=rel_path,
                abs_path=abs_path,
                size=size,
                sha256=digest,
                is_binary=is_bin,
            )

    return manifest
