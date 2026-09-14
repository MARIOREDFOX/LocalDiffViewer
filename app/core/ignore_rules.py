"""Glob-style ignore pattern matching, similar in spirit to .gitignore.

Supported pattern forms (kept intentionally simple and predictable):

    *.pyc            -> matches any file whose name matches the glob
    __pycache__/     -> matches a directory named __pycache__ anywhere,
                         and everything under it
    dist/            -> same as above, any directory named "dist"
    .git/            -> same
    build/output     -> matches that exact relative path (and children,
                         if it is a directory)
    /README.md       -> a leading slash anchors the pattern to the root
                         of the source being scanned

Matching is performed against the POSIX-style relative path of each entry
(always forward slashes, always relative to the scan root).
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field

DEFAULT_IGNORE_PATTERNS = [
    ".git/",
    "__pycache__/",
    "*.pyc",
    "node_modules/",
    ".venv/",
    "venv/",
    "dist/",
    "build/",
    "*.log",
    ".DS_Store",
]


@dataclass
class IgnoreRules:
    patterns: list[str] = field(default_factory=list)

    @classmethod
    def from_text(cls, text: str) -> "IgnoreRules":
        """Build rules from newline-separated pattern text (as typed in the UI)."""
        patterns = []
        for line in (text or "").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            patterns.append(line)
        return cls(patterns=patterns)

    def is_ignored(self, rel_path: str, is_dir: bool = False) -> bool:
        """Check whether ``rel_path`` (posix, relative to scan root) is ignored."""
        candidate = rel_path.strip("/")
        segments = candidate.split("/")

        for raw in self.patterns:
            pattern = raw.strip()
            if not pattern:
                continue

            anchored = pattern.startswith("/")
            dir_only = pattern.endswith("/")
            pat = pattern.strip("/")
            if not pat:
                continue

            if dir_only:
                # Directory pattern: match if any path segment equals the
                # pattern (non-anchored) or if the first segment does
                # (anchored).
                if anchored:
                    if segments and fnmatch.fnmatch(segments[0], pat):
                        return True
                else:
                    if any(fnmatch.fnmatch(seg, pat) for seg in segments[:-1] if not is_dir) or (
                        is_dir and any(fnmatch.fnmatch(seg, pat) for seg in segments)
                    ):
                        return True
                    # Also handle the case where the ignored dir itself is
                    # an ancestor of a file (already covered above), and
                    # the case where this entry *is* that directory.
                    if not is_dir and any(fnmatch.fnmatch(seg, pat) for seg in segments[:-1]):
                        return True
            else:
                if anchored:
                    if fnmatch.fnmatch(candidate, pat):
                        return True
                else:
                    # Match against the full path or the basename, and
                    # also allow the pattern to match any path segment
                    # (handy for things like "node_modules" with no
                    # trailing slash).
                    if fnmatch.fnmatch(candidate, pat) or fnmatch.fnmatch(segments[-1], pat):
                        return True
                    if fnmatch.fnmatch(candidate, f"*/{pat}") or fnmatch.fnmatch(candidate, f"{pat}/*"):
                        return True
        return False
