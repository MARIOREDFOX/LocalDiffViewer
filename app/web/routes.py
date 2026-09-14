"""HTTP API for the Local Diff Viewer.

Everything here is stateless w.r.t. the outside world: no external network
calls, no cloud storage. Comparison state lives only in the in-memory
`session_store` for the lifetime of the running process.
"""

from __future__ import annotations

import os
import time

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.core.comparator import CompareOptions, compare_sources
from app.core.diff_engine import DiffOptions
from app.core.diff_service import build_file_diff
from app.core.ignore_rules import IgnoreRules
from app.core.tree_builder import build_tree
from app.export.html_exporter import export_html
from app.export.json_exporter import export_json
from app.models.comparison import ChangeStatus
from app.web.ingest import ingest_folder_upload, ingest_zip_upload, strip_common_root
from app.web.session_store import Session, store

router = APIRouter()

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
MAX_UPLOAD_ITEMS = 20000  # sanity guard against pathological uploads


@router.get("/", response_class=HTMLResponse)
async def index():
    # The shell page has no server-side template variables, so it's served
    # as a plain static file rather than through a template engine.
    with open(os.path.join(_TEMPLATES_DIR, "index.html"), "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


def _bool(v: str | None) -> bool:
    return str(v).lower() in ("1", "true", "yes", "on")


@router.post("/api/compare")
async def api_compare(
    request: Request,
    left_kind: str = Form(...),
    right_kind: str = Form(...),
    left_label: str = Form(""),
    right_label: str = Form(""),
    ignore_patterns: str = Form(""),
    ignore_whitespace: str = Form("false"),
    ignore_blank_lines: str = Form("false"),
    ignore_case: str = Form("false"),
    detect_renames: str = Form("true"),
):
    form = await request.form()
    left_files = form.getlist("left_files")
    right_files = form.getlist("right_files")
    left_zip = form.get("left_zip")
    right_zip = form.get("right_zip")

    temp_dirs: list[str] = []

    async def resolve_side(kind: str, files: list, zip_file, default_label: str) -> tuple[str, str]:
        if kind == "zip":
            if not isinstance(zip_file, (UploadFile, StarletteUploadFile)) or not zip_file.filename:
                raise HTTPException(400, f"Missing ZIP upload for {default_label} side")
            d = await ingest_zip_upload(zip_file)
            temp_dirs.append(d)
            label = zip_file.filename
            return strip_common_root(d), label
        elif kind == "folder":
            real_files = [f for f in files if isinstance(f, (UploadFile, StarletteUploadFile)) and f.filename]
            if not real_files:
                raise HTTPException(400, f"No files uploaded for {default_label} side")
            if len(real_files) > MAX_UPLOAD_ITEMS:
                raise HTTPException(400, f"Too many files ({len(real_files)}) for {default_label} side")
            d = await ingest_folder_upload(real_files)
            temp_dirs.append(d)
            top = real_files[0].filename.split("/")[0] if "/" in real_files[0].filename else default_label
            return strip_common_root(d), top
        else:
            raise HTTPException(400, f"Invalid kind {kind!r} for {default_label} side")

    try:
        left_root, left_top = await resolve_side(left_kind, left_files, left_zip, "left")
        right_root, right_top = await resolve_side(right_kind, right_files, right_zip, "right")

        rules = IgnoreRules.from_text(ignore_patterns)
        options = CompareOptions(
            ignore_whitespace=_bool(ignore_whitespace),
            ignore_blank_lines=_bool(ignore_blank_lines),
            ignore_case=_bool(ignore_case),
            detect_renames=_bool(detect_renames),
        )

        result, left_manifest, right_manifest = compare_sources(
            left_root,
            right_root,
            left_label.strip() or left_top,
            right_label.strip() or right_top,
            ignore_rules=rules,
            options=options,
        )
    except HTTPException:
        for d in temp_dirs:
            _safe_rmtree(d)
        raise
    except Exception as exc:  # noqa: BLE001 - surface a clean 400 to the UI
        for d in temp_dirs:
            _safe_rmtree(d)
        raise HTTPException(400, f"Comparison failed: {exc}") from exc

    session = Session(
        result=result,
        left_manifest=left_manifest,
        right_manifest=right_manifest,
        temp_dirs=temp_dirs,
        compare_options=options,
    )
    store.put(session)

    return {"comparison_id": result.comparison_id}


def _safe_rmtree(path: str) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


def _get_session(comparison_id: str) -> Session:
    session = store.get(comparison_id)
    if session is None:
        raise HTTPException(404, "Comparison not found (it may have expired). Please run the comparison again.")
    return session


@router.get("/api/comparison/{comparison_id}/summary")
async def api_summary(comparison_id: str):
    session = _get_session(comparison_id)
    r = session.result
    return {
        "comparison_id": r.comparison_id,
        "left_label": r.left_label,
        "right_label": r.right_label,
        "duration_seconds": r.duration_seconds,
        "ignore_patterns": r.ignore_patterns,
        "warnings": r.warnings,
        "summary": {
            "total": r.summary.total,
            "added": r.summary.added,
            "deleted": r.summary.deleted,
            "modified": r.summary.modified,
            "unchanged": r.summary.unchanged,
            "renamed": r.summary.renamed,
        },
    }


@router.get("/api/comparison/{comparison_id}/tree")
async def api_tree(comparison_id: str):
    session = _get_session(comparison_id)
    return build_tree(session.result.changes)


@router.get("/api/comparison/{comparison_id}/changes")
async def api_changes(comparison_id: str, status: str = "", q: str = ""):
    session = _get_session(comparison_id)
    changes = session.result.changes

    if status and status != "all":
        try:
            wanted = ChangeStatus(status)
            changes = [c for c in changes if c.status == wanted]
        except ValueError:
            raise HTTPException(400, f"Invalid status filter: {status!r}")

    if q:
        ql = q.lower()
        changes = [c for c in changes if ql in c.rel_path.lower()]

    def to_dict(c):
        return {
            "status": c.status.value,
            "rel_path": c.rel_path,
            "left_path": c.left_path,
            "right_path": c.right_path,
            "size_left": c.size_left,
            "size_right": c.size_right,
            "is_binary": c.is_binary,
            "similarity": c.similarity,
        }

    return {"changes": [to_dict(c) for c in changes]}


@router.get("/api/comparison/{comparison_id}/diff")
async def api_diff(
    comparison_id: str,
    path: str,
    ignore_whitespace: str = "false",
    ignore_blank_lines: str = "false",
    ignore_case: str = "false",
    collapse_unchanged: str = "true",
    force: str = "false",
):
    session = _get_session(comparison_id)
    change = next((c for c in session.result.changes if c.rel_path == path), None)
    if change is None:
        raise HTTPException(404, f"No such file in this comparison: {path!r}")

    options = DiffOptions(
        ignore_whitespace=_bool(ignore_whitespace),
        ignore_blank_lines=_bool(ignore_blank_lines),
        ignore_case=_bool(ignore_case),
        collapse_unchanged=_bool(collapse_unchanged),
    )
    diff = build_file_diff(change, session.left_manifest, session.right_manifest, options, force=_bool(force))

    return {
        "rel_path": diff.rel_path,
        "is_binary": diff.is_binary,
        "identical": diff.identical,
        "left_size": diff.left_size,
        "right_size": diff.right_size,
        "left_hash": diff.left_hash,
        "right_hash": diff.right_hash,
        "left_missing": diff.left_missing,
        "right_missing": diff.right_missing,
        "additions": diff.additions,
        "deletions": diff.deletions,
        "truncated": diff.truncated,
        "skipped_reason": diff.skipped_reason,
        "unified": diff.unified,
        "rows": [
            {
                "op": row.op.value,
                "left_no": row.left_no,
                "left_text": row.left_text,
                "right_no": row.right_no,
                "right_text": row.right_text,
                "skipped_count": row.skipped_count,
            }
            for row in diff.rows
        ],
        "status": change.status.value,
    }


@router.get("/api/comparison/{comparison_id}/search")
async def api_search(comparison_id: str, q: str, content: str = "false", limit: int = 50):
    session = _get_session(comparison_id)
    if not q.strip():
        return {"query": q, "matches": []}

    ql = q.lower()
    matches = []
    search_content = _bool(content)

    for change in session.result.changes:
        name_hit = ql in change.rel_path.lower()
        content_hit = False
        snippet = None

        if search_content and not change.is_binary and len(matches) < limit:
            for manifest, p in (
                (session.right_manifest, change.right_path),
                (session.left_manifest, change.left_path),
            ):
                if content_hit or not p or p not in manifest:
                    continue
                entry = manifest[p]
                if entry.size > 2 * 1024 * 1024:
                    continue
                try:
                    with open(entry.abs_path, "rb") as fh:
                        text = fh.read(2 * 1024 * 1024).decode("utf-8", errors="ignore")
                except OSError:
                    continue
                idx = text.lower().find(ql)
                if idx != -1:
                    content_hit = True
                    start = max(0, idx - 40)
                    end = min(len(text), idx + len(q) + 40)
                    snippet = text[start:end].replace("\n", " ")

        if name_hit or content_hit:
            matches.append(
                {
                    "rel_path": change.rel_path,
                    "status": change.status.value,
                    "name_match": name_hit,
                    "content_match": content_hit,
                    "snippet": snippet,
                }
            )
        if len(matches) >= limit:
            break

    return {"query": q, "matches": matches}


@router.get("/api/comparison/{comparison_id}/export/json")
async def api_export_json(comparison_id: str, include_diffs: str = "false"):
    session = _get_session(comparison_id)
    file_diffs = None
    if _bool(include_diffs):
        file_diffs = {}
        for c in session.result.changes:
            if c.status in (ChangeStatus.MODIFIED, ChangeStatus.RENAMED) and not c.is_binary:
                file_diffs[c.rel_path] = build_file_diff(c, session.left_manifest, session.right_manifest)

    payload = export_json(session.result, file_diffs)
    filename = f"diff-{comparison_id[:8]}.json"
    return PlainTextResponse(
        payload,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/comparison/{comparison_id}/export/html")
async def api_export_html(comparison_id: str):
    session = _get_session(comparison_id)

    file_diffs = {}
    diffable = [
        c for c in session.result.changes
        if c.status in (ChangeStatus.MODIFIED, ChangeStatus.RENAMED) and not c.is_binary
    ]
    # Bound the number of full diffs embedded in the standalone report so a
    # huge comparison doesn't produce an unusably large HTML file.
    for c in diffable[:200]:
        file_diffs[c.rel_path] = build_file_diff(c, session.left_manifest, session.right_manifest, force=True)

    html_content = export_html(session.result, file_diffs)
    filename = f"diff-report-{comparison_id[:8]}.html"
    return HTMLResponse(
        html_content,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/api/comparison/{comparison_id}")
async def api_delete(comparison_id: str):
    ok = store.delete(comparison_id)
    if not ok:
        raise HTTPException(404, "Comparison not found")
    return {"deleted": True}


@router.get("/api/health")
async def health():
    return {"status": "ok", "time": time.time()}
