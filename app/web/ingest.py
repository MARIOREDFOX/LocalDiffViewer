"""Turns an incoming upload (a batch of folder files, or one ZIP file) into
a plain directory on disk that the scanner/comparator can work with.

This is the only place that touches uploaded bytes directly, so path
sanitization for folder uploads lives here (mirroring the ZIP-Slip
protection in ``archive.zip_handler`` for the ZIP case).
"""

from __future__ import annotations

import os
import tempfile

from fastapi import UploadFile

from app.archive.zip_handler import safe_extract_zip

CHUNK = 1024 * 1024


def _safe_join(root: str, rel_path: str) -> str:
    rel_path = rel_path.replace("\\", "/").lstrip("/")
    parts = [p for p in rel_path.split("/") if p not in ("", ".", "..")]
    target = os.path.join(root, *parts) if parts else root
    root_abs = os.path.abspath(root)
    target_abs = os.path.abspath(target)
    if not (target_abs == root_abs or target_abs.startswith(root_abs + os.sep)):
        raise ValueError(f"Unsafe upload path: {rel_path!r}")
    return target_abs


async def ingest_folder_upload(files: list[UploadFile]) -> str:
    """Write a batch of uploaded files (with relative-path filenames, as
    produced by a <input webkitdirectory> selection) into a fresh temp dir.
    """
    dest = tempfile.mkdtemp(prefix="diffviewer_")
    for f in files:
        rel_path = f.filename or "unnamed"
        # Browsers typically send "top-level-folder/sub/file.ext" as the
        # filename for directory uploads; keep everything after the first
        # path segment isn't necessary -- we just preserve the structure
        # as-is, since both sides get the same treatment.
        target = _safe_join(dest, rel_path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as out:
            while True:
                chunk = await f.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
        await f.close()
    return dest


async def ingest_zip_upload(zip_file: UploadFile) -> str:
    """Save an uploaded ZIP to disk and safely extract it into a temp dir."""
    fd, tmp_zip_path = tempfile.mkstemp(suffix=".zip", prefix="diffviewer_upload_")
    os.close(fd)
    try:
        with open(tmp_zip_path, "wb") as out:
            while True:
                chunk = await zip_file.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
        await zip_file.close()

        dest = tempfile.mkdtemp(prefix="diffviewer_")
        safe_extract_zip(tmp_zip_path, dest)
        return dest
    finally:
        os.remove(tmp_zip_path)


def strip_common_root(dest_dir: str) -> str:
    """If every uploaded file/ZIP entry shares one single top-level folder
    (e.g. "myproject/src/..."), drill into it so the comparison root is the
    project root rather than an extra synthetic wrapper directory. This
    mirrors what users expect from ``git diff`` style comparisons.
    """
    entries = [e for e in os.listdir(dest_dir) if not e.startswith("__MACOSX")]
    if len(entries) == 1:
        candidate = os.path.join(dest_dir, entries[0])
        if os.path.isdir(candidate):
            return candidate
    return dest_dir
