"""Top-level comparison engine.

Given two already-resolved plain-folder roots (ZIPs are extracted by the
caller beforehand), this module:

1. Scans both sides into manifests (see ``scanner.scan_folder``).
2. Diffs the two path sets to find added / deleted / common paths.
3. Splits common paths into modified vs. unchanged by comparing hashes.
4. Attempts to pair up deleted+added files as renames, first by exact
   content hash, then (for text files, when the candidate set is small
   enough to make this cheap) by content similarity.
5. Produces a `ComparisonResult` with per-file status plus a summary.

Line-level diffs are *not* generated here -- that's deliberately deferred
to `diff_engine`, invoked on demand only for the file the user opens, so
comparing a large tree stays fast.
"""

from __future__ import annotations

import difflib
import time
import uuid
from dataclasses import dataclass

from app.core.file_detector import is_text_path, read_sample
from app.core.ignore_rules import IgnoreRules
from app.core.scanner import scan_folder
from app.models.comparison import ChangeStatus, ComparisonResult, ComparisonSummary, FileChange
from app.models.file_entry import FileEntry

# Only attempt O(n*m) similarity-based rename detection when both candidate
# pools are small enough that the quadratic cost stays negligible.
RENAME_SIMILARITY_MAX_CANDIDATES = 150
RENAME_SIMILARITY_THRESHOLD = 0.6
RENAME_CONTENT_SAMPLE_BYTES = 64 * 1024


@dataclass
class CompareOptions:
    ignore_whitespace: bool = False
    ignore_blank_lines: bool = False
    ignore_case: bool = False
    detect_renames: bool = True


def _read_text_sample_for_similarity(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            raw = fh.read(RENAME_CONTENT_SAMPLE_BYTES)
        return raw.decode("utf-8", errors="replace")
    except OSError:
        return ""


def _detect_renames(
    deleted: dict[str, FileEntry],
    added: dict[str, FileEntry],
) -> list[tuple[str, str, float]]:
    """Return a list of (deleted_path, added_path, similarity) rename pairs.

    Mutates nothing; caller is responsible for removing paired entries from
    the deleted/added dicts.
    """
    pairs: list[tuple[str, str, float]] = []
    used_added: set[str] = set()

    # Pass 1: exact hash match (pure rename/move, content identical).
    by_hash: dict[str, list[str]] = {}
    for path, entry in added.items():
        if entry.is_dir:
            continue
        by_hash.setdefault(entry.sha256, []).append(path)

    for dpath, dentry in list(deleted.items()):
        if dentry.is_dir:
            continue
        candidates = [p for p in by_hash.get(dentry.sha256, []) if p not in used_added]
        if candidates:
            apath = candidates[0]
            pairs.append((dpath, apath, 1.0))
            used_added.add(apath)

    # Pass 2: content-similarity match for text files, bounded in size so
    # it never becomes a perf trap on huge trees.
    remaining_deleted = {p: e for p, e in deleted.items() if p not in {x[0] for x in pairs} and not e.is_dir and not e.is_binary}
    remaining_added = {p: e for p, e in added.items() if p not in used_added and not e.is_dir and not e.is_binary}

    if remaining_deleted and remaining_added and (
        len(remaining_deleted) * len(remaining_added) <= RENAME_SIMILARITY_MAX_CANDIDATES ** 2
    ):
        added_samples = {p: _read_text_sample_for_similarity(e.abs_path) for p, e in remaining_added.items()}
        for dpath, dentry in remaining_deleted.items():
            d_sample = _read_text_sample_for_similarity(dentry.abs_path)
            if not d_sample.strip():
                continue
            best_path, best_ratio = None, 0.0
            for apath, a_sample in added_samples.items():
                if apath in used_added:
                    continue
                if not a_sample.strip():
                    continue
                ratio = difflib.SequenceMatcher(a=d_sample, b=a_sample, autojunk=False).quick_ratio()
                if ratio > best_ratio:
                    best_ratio, best_path = ratio, apath
            if best_path is not None and best_ratio >= RENAME_SIMILARITY_THRESHOLD:
                pairs.append((dpath, best_path, best_ratio))
                used_added.add(best_path)

    return pairs


def compare_sources(
    left_root: str,
    right_root: str,
    left_label: str,
    right_label: str,
    ignore_rules: IgnoreRules | None = None,
    options: CompareOptions | None = None,
) -> tuple[ComparisonResult, dict[str, FileEntry], dict[str, FileEntry]]:
    start = time.perf_counter()
    ignore_rules = ignore_rules or IgnoreRules()
    options = options or CompareOptions()

    left_manifest = scan_folder(left_root, ignore_rules)
    right_manifest = scan_folder(right_root, ignore_rules)

    left_paths = set(left_manifest)
    right_paths = set(right_manifest)

    added_paths = right_paths - left_paths
    deleted_paths = left_paths - right_paths
    common_paths = left_paths & right_paths

    deleted_files = {p: e for p, e in left_manifest.items() if p in deleted_paths and not e.is_dir}
    added_files = {p: e for p, e in right_manifest.items() if p in added_paths and not e.is_dir}

    rename_pairs: list[tuple[str, str, float]] = []
    if options.detect_renames:
        rename_pairs = _detect_renames(deleted_files, added_files)

    renamed_left = {p for p, _, _ in rename_pairs}
    renamed_right = {p for _, p, _ in rename_pairs}

    changes: list[FileChange] = []

    for dpath, apath, ratio in rename_pairs:
        le = left_manifest[dpath]
        re_ = right_manifest[apath]
        status = ChangeStatus.RENAMED
        changes.append(
            FileChange(
                status=status,
                rel_path=apath,
                left_path=dpath,
                right_path=apath,
                size_left=le.size,
                size_right=re_.size,
                hash_left=le.sha256,
                hash_right=re_.sha256,
                is_binary=le.is_binary or re_.is_binary,
                similarity=round(ratio, 3),
            )
        )

    for p in sorted(deleted_paths):
        entry = left_manifest[p]
        if entry.is_dir or p in renamed_left:
            continue
        changes.append(
            FileChange(
                status=ChangeStatus.DELETED,
                rel_path=p,
                left_path=p,
                size_left=entry.size,
                hash_left=entry.sha256,
                is_binary=entry.is_binary,
            )
        )

    for p in sorted(added_paths):
        entry = right_manifest[p]
        if entry.is_dir or p in renamed_right:
            continue
        changes.append(
            FileChange(
                status=ChangeStatus.ADDED,
                rel_path=p,
                right_path=p,
                size_right=entry.size,
                hash_right=entry.sha256,
                is_binary=entry.is_binary,
            )
        )

    for p in sorted(common_paths):
        le = left_manifest[p]
        re_ = right_manifest[p]
        if le.is_dir or re_.is_dir:
            continue
        if le.sha256 == re_.sha256:
            status = ChangeStatus.UNCHANGED
        else:
            status = ChangeStatus.MODIFIED
        changes.append(
            FileChange(
                status=status,
                rel_path=p,
                left_path=p,
                right_path=p,
                size_left=le.size,
                size_right=re_.size,
                hash_left=le.sha256,
                hash_right=re_.sha256,
                is_binary=le.is_binary or re_.is_binary,
            )
        )

    summary = ComparisonSummary(
        total=len(changes),
        added=sum(1 for c in changes if c.status == ChangeStatus.ADDED),
        deleted=sum(1 for c in changes if c.status == ChangeStatus.DELETED),
        modified=sum(1 for c in changes if c.status == ChangeStatus.MODIFIED),
        unchanged=sum(1 for c in changes if c.status == ChangeStatus.UNCHANGED),
        renamed=sum(1 for c in changes if c.status == ChangeStatus.RENAMED),
    )

    result = ComparisonResult(
        comparison_id=str(uuid.uuid4()),
        left_label=left_label,
        right_label=right_label,
        summary=summary,
        changes=sorted(changes, key=lambda c: c.rel_path),
        duration_seconds=round(time.perf_counter() - start, 4),
        ignore_patterns=list(ignore_rules.patterns),
    )
    return result, left_manifest, right_manifest
