"""Streaming hash helpers.

Files are never loaded fully into memory just to compute a hash -- we read
them in fixed-size chunks so that even very large files can be hashed with a
constant memory footprint.
"""

from __future__ import annotations

import hashlib

CHUNK_SIZE = 1024 * 1024  # 1 MiB


def hash_file(path: str, chunk_size: int = CHUNK_SIZE) -> str:
    """Return the hex SHA-256 digest of the file at ``path``."""
    hasher = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
