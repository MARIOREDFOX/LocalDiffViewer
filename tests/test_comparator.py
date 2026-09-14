import os

import pytest

from app.core.comparator import CompareOptions, compare_sources
from app.core.ignore_rules import IgnoreRules
from app.models.comparison import ChangeStatus


def write(path, content, binary=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "wb" if binary else "w"
    with open(path, mode) as f:
        f.write(content)


def status_map(result):
    return {c.rel_path: c.status for c in result.changes}


def test_identical_folders(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    write(str(left / "a.txt"), "hello\nworld\n")
    write(str(right / "a.txt"), "hello\nworld\n")

    result, _, _ = compare_sources(str(left), str(right), "left", "right")
    assert result.summary.unchanged == 1
    assert result.summary.modified == 0
    assert result.summary.added == 0
    assert result.summary.deleted == 0


def test_added_file(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    write(str(left / "a.txt"), "hi\n")
    write(str(right / "a.txt"), "hi\n")
    write(str(right / "b.txt"), "new\n")

    result, _, _ = compare_sources(str(left), str(right), "left", "right")
    sm = status_map(result)
    assert sm["b.txt"] == ChangeStatus.ADDED
    assert result.summary.added == 1


def test_deleted_file(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    write(str(left / "a.txt"), "hi\n")
    write(str(left / "gone.txt"), "bye\n")
    write(str(right / "a.txt"), "hi\n")

    result, _, _ = compare_sources(str(left), str(right), "left", "right")
    sm = status_map(result)
    assert sm["gone.txt"] == ChangeStatus.DELETED
    assert result.summary.deleted == 1


def test_modified_text_file(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    write(str(left / "a.py"), "def f():\n    return 1\n")
    write(str(right / "a.py"), "def f():\n    return 2\n")

    result, _, _ = compare_sources(str(left), str(right), "left", "right")
    sm = status_map(result)
    assert sm["a.py"] == ChangeStatus.MODIFIED
    assert result.summary.modified == 1


def test_unchanged_file(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    write(str(left / "readme.md"), "# Title\n")
    write(str(right / "readme.md"), "# Title\n")

    result, _, _ = compare_sources(str(left), str(right), "left", "right")
    sm = status_map(result)
    assert sm["readme.md"] == ChangeStatus.UNCHANGED


def test_renamed_file_exact_content(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    write(str(left / "old_name.py"), "print('hello world')\n")
    write(str(right / "new_name.py"), "print('hello world')\n")

    result, _, _ = compare_sources(str(left), str(right), "left", "right")
    renamed = [c for c in result.changes if c.status == ChangeStatus.RENAMED]
    assert len(renamed) == 1
    assert renamed[0].left_path == "old_name.py"
    assert renamed[0].right_path == "new_name.py"
    assert result.summary.added == 0
    assert result.summary.deleted == 0


def test_binary_file_changed(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    write(str(left / "img.png"), b"\x89PNG\r\n\x1a\nAAAA", binary=True)
    write(str(right / "img.png"), b"\x89PNG\r\n\x1a\nBBBB", binary=True)

    result, _, _ = compare_sources(str(left), str(right), "left", "right")
    change = next(c for c in result.changes if c.rel_path == "img.png")
    assert change.status == ChangeStatus.MODIFIED
    assert change.is_binary is True


def test_binary_file_unchanged(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    write(str(left / "img.png"), b"\x89PNG\r\n\x1a\nAAAA", binary=True)
    write(str(right / "img.png"), b"\x89PNG\r\n\x1a\nAAAA", binary=True)

    result, _, _ = compare_sources(str(left), str(right), "left", "right")
    change = next(c for c in result.changes if c.rel_path == "img.png")
    assert change.status == ChangeStatus.UNCHANGED
    assert change.is_binary is True


def test_ignore_patterns(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    write(str(left / "keep.py"), "1\n")
    write(str(left / "__pycache__" / "x.pyc"), b"junk", binary=True)
    write(str(right / "keep.py"), "1\n")
    write(str(right / "__pycache__" / "x.pyc"), b"different junk", binary=True)
    write(str(right / "app.log"), "log line\n")

    rules = IgnoreRules.from_text("__pycache__/\n*.log\n")
    result, _, _ = compare_sources(str(left), str(right), "left", "right", ignore_rules=rules)
    paths = {c.rel_path for c in result.changes}
    assert "__pycache__/x.pyc" not in paths
    assert "app.log" not in paths
    assert result.summary.total == 1


def test_empty_directories(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    os.makedirs(str(left / "emptydir"))
    os.makedirs(str(right / "emptydir"))
    write(str(left / "a.txt"), "x\n")
    write(str(right / "a.txt"), "x\n")

    # Should not crash, and the empty dir shouldn't appear as a "file" change.
    result, _, _ = compare_sources(str(left), str(right), "left", "right")
    assert all(c.rel_path != "emptydir" for c in result.changes)


def test_nested_directories(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    write(str(left / "a" / "b" / "c" / "deep.txt"), "1\n")
    write(str(right / "a" / "b" / "c" / "deep.txt"), "2\n")

    result, _, _ = compare_sources(str(left), str(right), "left", "right")
    sm = status_map(result)
    assert sm["a/b/c/deep.txt"] == ChangeStatus.MODIFIED


def test_unicode_and_spaces_filenames(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    write(str(left / "résumé 文件.txt"), "hello\n")
    write(str(right / "résumé 文件.txt"), "hello there\n")

    result, _, _ = compare_sources(str(left), str(right), "left", "right")
    sm = status_map(result)
    assert sm["résumé 文件.txt"] == ChangeStatus.MODIFIED


def test_line_ending_difference_lf_vs_crlf(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    write(str(left / "a.txt"), "line1\nline2\n")
    write(str(right / "a.txt"), "line1\r\nline2\r\n")

    result, _, _ = compare_sources(str(left), str(right), "left", "right")
    sm = status_map(result)
    # Different bytes -> different hash -> modified (even though the visible
    # text is the same; this is documented behavior, hashing is byte-exact).
    assert sm["a.txt"] == ChangeStatus.MODIFIED
