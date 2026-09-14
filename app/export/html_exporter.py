"""Generate a single, self-contained HTML report for a comparison.

The output file has no external dependencies (CSS/JS are inlined) so it can
be opened directly in a browser, emailed, or archived, without the app
running.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone

from app.models.comparison import ChangeStatus, ComparisonResult
from app.models.diff_result import FileDiff, LineOp

_STATUS_LABEL = {
    ChangeStatus.ADDED: ("Added", "#22c55e"),
    ChangeStatus.DELETED: ("Deleted", "#ef4444"),
    ChangeStatus.MODIFIED: ("Modified", "#eab308"),
    ChangeStatus.UNCHANGED: ("Unchanged", "#6b7280"),
    ChangeStatus.RENAMED: ("Renamed", "#3b82f6"),
}

_CSS = """
:root{--bg:#0d1117;--panel:#161b22;--border:#30363d;--text:#c9d1d9;--muted:#8b949e;
--add:#1a4620;--add-text:#7ee787;--del:#4a1d1d;--del-text:#ffa198;--accent:#58a6ff;}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;margin:0;padding:0;}
header{padding:24px 32px;border-bottom:1px solid var(--border);background:var(--panel);}
h1{margin:0 0 4px 0;font-size:20px}
.sub{color:var(--muted);font-size:13px}
.container{padding:24px 32px;max-width:1400px;margin:0 auto;}
.summary{display:flex;gap:16px;flex-wrap:wrap;margin:20px 0;}
.badge{border:1px solid var(--border);border-radius:8px;padding:10px 16px;background:var(--panel);min-width:110px}
.badge .n{font-size:22px;font-weight:700}
.badge .l{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
table.files{width:100%;border-collapse:collapse;margin:16px 0 32px 0;font-size:13px}
table.files th,table.files td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--border)}
table.files th{color:var(--muted);font-weight:600;text-transform:uppercase;font-size:11px}
.status-pill{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600;color:#0d1117}
h2{border-top:1px solid var(--border);padding-top:24px;margin-top:8px;font-size:16px}
.diff-file{margin-bottom:36px;border:1px solid var(--border);border-radius:8px;overflow:hidden}
.diff-file .fh{background:var(--panel);padding:8px 14px;font-family:ui-monospace,Consolas,monospace;font-size:13px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between}
table.sbs{width:100%;border-collapse:collapse;font-family:ui-monospace,Consolas,"SFMono-Regular",monospace;font-size:12.5px}
table.sbs td{padding:1px 8px;white-space:pre;vertical-align:top}
td.ln{color:var(--muted);text-align:right;width:40px;user-select:none;border-right:1px solid var(--border)}
tr.add td.code{background:var(--add);color:var(--add-text)}
tr.del td.code{background:var(--del);color:var(--del-text)}
tr.eq td.code{color:var(--text)}
tr.skip td{color:var(--muted);background:var(--panel);text-align:center;font-family:inherit}
.binary-box{padding:16px;font-size:13px}
.binary-box code{color:var(--accent)}
footer{color:var(--muted);font-size:12px;padding:24px 32px;text-align:center}
"""


def _status_pill(status: ChangeStatus) -> str:
    label, color = _STATUS_LABEL[status]
    return f'<span class="status-pill" style="background:{color}">{label}</span>'


def _render_side_by_side_table(diff: FileDiff) -> str:
    rows_html = []
    for row in diff.rows:
        if row.op == LineOp.CONTEXT_SKIP:
            rows_html.append(
                f'<tr class="skip"><td colspan="4">&#8942; {row.skipped_count} unchanged line(s) hidden &#8942;</td></tr>'
            )
            continue

        cls = {
            LineOp.EQUAL: "eq",
            LineOp.ADD: "add",
            LineOp.DELETE: "del",
            LineOp.REPLACE: "del",  # left cell rendered red, right cell green below
        }.get(row.op, "eq")

        left_no = row.left_no if row.left_no is not None else ""
        right_no = row.right_no if row.right_no is not None else ""
        left_text = html.escape(row.left_text) if row.left_text is not None else ""
        right_text = html.escape(row.right_text) if row.right_text is not None else ""

        if row.op == LineOp.REPLACE:
            rows_html.append(
                f'<tr class="del"><td class="ln">{left_no}</td><td class="code">{left_text}</td>'
                f'<td class="ln">{right_no}</td><td class="code" style="background:#1a4620;color:#7ee787">{right_text}</td></tr>'
            )
        else:
            rows_html.append(
                f'<tr class="{cls}"><td class="ln">{left_no}</td><td class="code">{left_text}</td>'
                f'<td class="ln">{right_no}</td><td class="code">{right_text}</td></tr>'
            )
    return (
        '<table class="sbs"><colgroup><col style="width:40px"><col style="width:47%">'
        '<col style="width:40px"><col style="width:47%"></colgroup>' + "".join(rows_html) + "</table>"
    )


def _render_file_diff(diff: FileDiff) -> str:
    header = (
        f'<div class="fh"><span>{html.escape(diff.rel_path)}</span>'
        f'<span>+{diff.additions} / -{diff.deletions}</span></div>'
    )
    if diff.is_binary:
        body = (
            f'<div class="binary-box">Binary file changed.<br>'
            f'Left: {diff.left_size or 0} bytes &nbsp; sha256=<code>{diff.left_hash}</code><br>'
            f'Right: {diff.right_size or 0} bytes &nbsp; sha256=<code>{diff.right_hash}</code></div>'
        )
    elif diff.skipped_reason:
        body = f'<div class="binary-box">{html.escape(diff.skipped_reason)}</div>'
    else:
        body = _render_side_by_side_table(diff)
    return f'<div class="diff-file">{header}{body}</div>'


def export_html(result: ComparisonResult, file_diffs: dict[str, FileDiff] | None = None) -> str:
    file_diffs = file_diffs or {}
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    summary = result.summary
    badges = "".join(
        f'<div class="badge"><div class="n">{n}</div><div class="l">{label}</div></div>'
        for label, n in [
            ("Total", summary.total),
            ("Added", summary.added),
            ("Deleted", summary.deleted),
            ("Modified", summary.modified),
            ("Renamed", summary.renamed),
            ("Unchanged", summary.unchanged),
        ]
    )

    rows = []
    for c in result.changes:
        rows.append(
            "<tr>"
            f"<td>{_status_pill(c.status)}</td>"
            f"<td>{html.escape(c.rel_path)}</td>"
            f"<td>{'binary' if c.is_binary else 'text'}</td>"
            f"<td>{c.size_left if c.size_left is not None else '—'}</td>"
            f"<td>{c.size_right if c.size_right is not None else '—'}</td>"
            "</tr>"
        )
    files_table = (
        '<table class="files"><thead><tr><th>Status</th><th>Path</th><th>Type</th>'
        "<th>Left size</th><th>Right size</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )

    diffs_html = "".join(_render_file_diff(fd) for fd in file_diffs.values())

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Diff Report: {html.escape(result.left_label)} vs {html.escape(result.right_label)}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <h1>Local Diff Viewer &mdash; Comparison Report</h1>
  <div class="sub">{html.escape(result.left_label)} &nbsp;&rarr;&nbsp; {html.escape(result.right_label)}
   &nbsp;|&nbsp; generated {generated} &nbsp;|&nbsp; took {result.duration_seconds}s</div>
</header>
<div class="container">
  <div class="summary">{badges}</div>
  <h2>All files ({summary.total})</h2>
  {files_table}
  {"<h2>Detailed diffs</h2>" + diffs_html if diffs_html else ""}
</div>
<footer>Generated locally by Local Diff Viewer &mdash; no data left this machine.</footer>
</body>
</html>"""
