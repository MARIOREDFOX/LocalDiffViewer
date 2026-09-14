"""Serialize a ComparisonResult (optionally with per-file diffs) to JSON."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Optional

from app.models.comparison import ComparisonResult
from app.models.diff_result import FileDiff


def comparison_to_dict(result: ComparisonResult, file_diffs: Optional[dict[str, FileDiff]] = None) -> dict:
    payload = {
        "comparison_id": result.comparison_id,
        "left_label": result.left_label,
        "right_label": result.right_label,
        "duration_seconds": result.duration_seconds,
        "ignore_patterns": result.ignore_patterns,
        "warnings": result.warnings,
        "summary": asdict(result.summary),
        "changes": [
            {**asdict(c), "status": c.status.value}
            for c in result.changes
        ],
    }
    if file_diffs:
        payload["file_diffs"] = {
            path: {**asdict(fd), "rows": [asdict(r) | {"op": r.op.value} for r in fd.rows]}
            for path, fd in file_diffs.items()
        }
    return payload


def export_json(result: ComparisonResult, file_diffs: Optional[dict[str, FileDiff]] = None) -> str:
    return json.dumps(comparison_to_dict(result, file_diffs), indent=2, ensure_ascii=False)
