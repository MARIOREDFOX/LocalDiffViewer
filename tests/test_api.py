import io
import os
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def make_zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_folder_vs_folder_via_api(tmp_path):
    resp = client.post(
        "/api/compare",
        data={
            "left_kind": "folder",
            "right_kind": "folder",
            "left_label": "L",
            "right_label": "R",
            "ignore_patterns": "",
            "ignore_whitespace": "false",
            "ignore_blank_lines": "false",
            "ignore_case": "false",
            "detect_renames": "true",
        },
        files=[
            ("left_files", ("proj/a.txt", b"hello\n", "text/plain")),
            ("left_files", ("proj/b.txt", b"world\n", "text/plain")),
            ("right_files", ("proj/a.txt", b"hello\n", "text/plain")),
            ("right_files", ("proj/b.txt", b"world!\n", "text/plain")),
        ],
    )
    assert resp.status_code == 200
    cid = resp.json()["comparison_id"]

    summary = client.get(f"/api/comparison/{cid}/summary").json()
    assert summary["summary"]["modified"] == 1
    assert summary["summary"]["unchanged"] == 1

    diff = client.get(f"/api/comparison/{cid}/diff", params={"path": "b.txt"}).json()
    assert diff["additions"] >= 1
    client.delete(f"/api/comparison/{cid}")


def test_zip_vs_zip_via_api():
    left_zip = make_zip_bytes({"src/main.py": b"print(1)\n", "readme.md": b"# hi\n"})
    right_zip = make_zip_bytes({"src/main.py": b"print(2)\n", "readme.md": b"# hi\n", "new.txt": b"new\n"})

    resp = client.post(
        "/api/compare",
        data={
            "left_kind": "zip", "right_kind": "zip",
            "left_label": "", "right_label": "",
            "ignore_patterns": "", "ignore_whitespace": "false",
            "ignore_blank_lines": "false", "ignore_case": "false", "detect_renames": "true",
        },
        files={
            "left_zip": ("left.zip", left_zip, "application/zip"),
            "right_zip": ("right.zip", right_zip, "application/zip"),
        },
    )
    assert resp.status_code == 200
    cid = resp.json()["comparison_id"]
    summary = client.get(f"/api/comparison/{cid}/summary").json()
    assert summary["summary"]["added"] == 1
    assert summary["summary"]["modified"] == 1
    assert summary["summary"]["unchanged"] == 1
    client.delete(f"/api/comparison/{cid}")


def test_folder_vs_zip_via_api():
    right_zip = make_zip_bytes({"a.txt": b"changed\n"})
    resp = client.post(
        "/api/compare",
        data={
            "left_kind": "folder", "right_kind": "zip",
            "left_label": "", "right_label": "",
            "ignore_patterns": "", "ignore_whitespace": "false",
            "ignore_blank_lines": "false", "ignore_case": "false", "detect_renames": "true",
        },
        files=[("left_files", ("a.txt", b"original\n", "text/plain"))]
        + [("right_zip", ("right.zip", right_zip, "application/zip"))],
    )
    assert resp.status_code == 200
    cid = resp.json()["comparison_id"]
    summary = client.get(f"/api/comparison/{cid}/summary").json()
    assert summary["summary"]["modified"] == 1
    client.delete(f"/api/comparison/{cid}")


def test_malicious_zip_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../evil.txt", "pwned")
    evil_zip = buf.getvalue()

    good_zip = make_zip_bytes({"a.txt": b"x\n"})

    resp = client.post(
        "/api/compare",
        data={
            "left_kind": "zip", "right_kind": "zip",
            "left_label": "", "right_label": "",
            "ignore_patterns": "", "ignore_whitespace": "false",
            "ignore_blank_lines": "false", "ignore_case": "false", "detect_renames": "true",
        },
        files={
            "left_zip": ("evil.zip", evil_zip, "application/zip"),
            "right_zip": ("right.zip", good_zip, "application/zip"),
        },
    )
    # Should be a clean 400, not a server crash or an escape onto disk.
    assert resp.status_code == 400


def test_export_json_and_html():
    resp = client.post(
        "/api/compare",
        data={
            "left_kind": "folder", "right_kind": "folder",
            "left_label": "", "right_label": "",
            "ignore_patterns": "", "ignore_whitespace": "false",
            "ignore_blank_lines": "false", "ignore_case": "false", "detect_renames": "true",
        },
        files=[
            ("left_files", ("a.py", b"x = 1\n", "text/plain")),
            ("right_files", ("a.py", b"x = 2\n", "text/plain")),
        ],
    )
    cid = resp.json()["comparison_id"]

    j = client.get(f"/api/comparison/{cid}/export/json", params={"include_diffs": "true"})
    assert j.status_code == 200
    assert "file_diffs" in j.text

    h = client.get(f"/api/comparison/{cid}/export/html")
    assert h.status_code == 200
    assert "<html" in h.text
    assert "a.py" in h.text
    client.delete(f"/api/comparison/{cid}")


def test_search_endpoint():
    resp = client.post(
        "/api/compare",
        data={
            "left_kind": "folder", "right_kind": "folder",
            "left_label": "", "right_label": "",
            "ignore_patterns": "", "ignore_whitespace": "false",
            "ignore_blank_lines": "false", "ignore_case": "false", "detect_renames": "true",
        },
        files=[
            ("left_files", ("auth.py", b"def login(): pass\n", "text/plain")),
            ("right_files", ("auth.py", b"def login(): pass\n", "text/plain")),
            ("right_files", ("user_service.py", b"def get_user(): pass\n", "text/plain")),
        ],
    )
    cid = resp.json()["comparison_id"]
    res = client.get(f"/api/comparison/{cid}/search", params={"q": "user"})
    paths = [m["rel_path"] for m in res.json()["matches"]]
    assert "user_service.py" in paths
    client.delete(f"/api/comparison/{cid}")


def test_large_file_is_skipped_by_default_and_forceable():
    # ~20k lines/side keeps us under the hard line-count safety cap while
    # still comfortably exceeding the 3MB byte-size auto-skip threshold.
    big_left = ("x" * 100 + "\n") * 20000
    big_right = big_left.replace("x" * 100 + "\n", "y" * 100 + "\n", 1)

    resp = client.post(
        "/api/compare",
        data={
            "left_kind": "folder", "right_kind": "folder",
            "left_label": "", "right_label": "",
            "ignore_patterns": "", "ignore_whitespace": "false",
            "ignore_blank_lines": "false", "ignore_case": "false", "detect_renames": "true",
        },
        files=[
            ("left_files", ("big.txt", big_left.encode(), "text/plain")),
            ("right_files", ("big.txt", big_right.encode(), "text/plain")),
        ],
    )
    cid = resp.json()["comparison_id"]

    diff = client.get(f"/api/comparison/{cid}/diff", params={"path": "big.txt"}).json()
    assert diff["truncated"] is True
    assert diff["rows"] == []

    forced = client.get(f"/api/comparison/{cid}/diff", params={"path": "big.txt", "force": "true"}).json()
    assert forced["truncated"] is False
    assert len(forced["rows"]) > 0
    client.delete(f"/api/comparison/{cid}")


def test_extreme_line_count_is_capped_even_when_forced():
    """Repetitive-content files (a difflib worst case for autojunk=False)
    must still return quickly and predictably, even under `force=true`."""
    huge_left = "line\n" * 80000
    huge_right = huge_left.replace("line\n", "LINE\n", 1)

    resp = client.post(
        "/api/compare",
        data={
            "left_kind": "folder", "right_kind": "folder",
            "left_label": "", "right_label": "",
            "ignore_patterns": "", "ignore_whitespace": "false",
            "ignore_blank_lines": "false", "ignore_case": "false", "detect_renames": "true",
        },
        files=[
            ("left_files", ("huge.txt", huge_left.encode(), "text/plain")),
            ("right_files", ("huge.txt", huge_right.encode(), "text/plain")),
        ],
    )
    cid = resp.json()["comparison_id"]

    forced = client.get(
        f"/api/comparison/{cid}/diff", params={"path": "huge.txt", "force": "true"}
    ).json()
    assert forced["truncated"] is True
    assert forced["rows"] == []
    assert "too many lines" in forced["skipped_reason"]
    client.delete(f"/api/comparison/{cid}")
