"""Safe ZIP archive handling.

This module is the only place in the codebase that touches ``zipfile``
directly for extraction, so all path-traversal ("Zip Slip") protection is
centralized here.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path


class UnsafeZipError(Exception):
    """Raised when a ZIP entry would extract outside the target directory."""


def is_zip_file(path: str) -> bool:
    try:
        return zipfile.is_zipfile(path)
    except OSError:
        return False


def _safe_member_path(dest_root: str, member_name: str) -> str:
    """Resolve a ZIP member name to an absolute path guaranteed to live
    inside ``dest_root``, raising :class:`UnsafeZipError` otherwise.
    """
    # Normalize backslashes (Windows-built zips) to forward slashes, strip
    # any leading path separators / drive letters that could be used to
    # escape the destination.
    normalized = member_name.replace("\\", "/")
    normalized = normalized.lstrip("/")

    # Reject absolute Windows paths like "C:/evil".
    if len(normalized) >= 2 and normalized[1] == ":":
        raise UnsafeZipError(f"Refusing to extract entry with drive letter: {member_name!r}")

    dest_root_abs = os.path.abspath(dest_root)
    target = os.path.abspath(os.path.join(dest_root_abs, normalized))

    # The classic Zip-Slip check: the resolved target must remain within
    # dest_root after normalization (this catches "../../etc/passwd" style
    # entries).
    if not (target == dest_root_abs or target.startswith(dest_root_abs + os.sep)):
        raise UnsafeZipError(f"Unsafe ZIP entry path detected: {member_name!r}")

    return target


def safe_extract_zip(zip_path: str, dest_dir: str) -> str:
    """Extract ``zip_path`` into ``dest_dir``, validating every member path.

    Returns ``dest_dir``. Symlinks are not honored (written out as plain
    files/skipped) and no file is ever executed.
    """
    os.makedirs(dest_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            target = _safe_member_path(dest_dir, info.filename)

            if info.is_dir() or info.filename.endswith("/"):
                os.makedirs(target, exist_ok=True)
                continue

            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                # Stream in chunks rather than reading the whole entry into
                # memory at once, to keep large-archive extraction cheap.
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)

    return dest_dir


def make_zip(source_dir: str, zip_path: str) -> str:
    """Utility used by tests / export to build a ZIP from a directory tree."""
    source = Path(source_dir)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                zf.write(path, arcname=str(path.relative_to(source)))
    return zip_path
