from app.core.diff_engine import (
    DiffOptions,
    generate_side_by_side,
    generate_unified_diff,
    split_lines,
)
from app.models.diff_result import LineOp


def test_split_lines_handles_crlf():
    assert split_lines("a\r\nb\r\n") == ["a", "b"]
    assert split_lines("a\nb") == ["a", "b"]
    assert split_lines("") == []


def test_side_by_side_simple_modification():
    left = split_lines("def f():\n    return 1\n")
    right = split_lines("def f():\n    return 2\n")
    rows, additions, deletions = generate_side_by_side(left, right, DiffOptions(collapse_unchanged=False))

    assert additions == 1
    assert deletions == 1
    ops = [r.op for r in rows]
    assert LineOp.EQUAL in ops
    assert LineOp.REPLACE in ops


def test_side_by_side_pure_addition():
    left = split_lines("a\nb\n")
    right = split_lines("a\nb\nc\n")
    rows, additions, deletions = generate_side_by_side(left, right, DiffOptions(collapse_unchanged=False))
    assert additions == 1
    assert deletions == 0
    add_rows = [r for r in rows if r.op == LineOp.ADD]
    assert len(add_rows) == 1
    assert add_rows[0].right_text == "c"


def test_ignore_whitespace_option():
    left = split_lines("x = 1\n")
    right = split_lines("x=1\n")
    rows, additions, deletions = generate_side_by_side(
        left, right, DiffOptions(ignore_whitespace=True, collapse_unchanged=False)
    )
    assert additions == 0
    assert deletions == 0
    assert all(r.op == LineOp.EQUAL for r in rows)


def test_ignore_case_option():
    left = split_lines("Hello\n")
    right = split_lines("hello\n")
    rows, additions, deletions = generate_side_by_side(
        left, right, DiffOptions(ignore_case=True, collapse_unchanged=False)
    )
    assert additions == 0
    assert deletions == 0


def test_ignore_blank_lines_option():
    left = split_lines("a\n\nb\n")
    right = split_lines("a\nb\n")
    rows, additions, deletions = generate_side_by_side(
        left, right, DiffOptions(ignore_blank_lines=True, collapse_unchanged=False)
    )
    assert additions == 0
    assert deletions == 0


def test_collapse_unchanged_creates_skip_row():
    left = split_lines("\n".join(str(i) for i in range(1, 21)) + "\nCHANGED\n")
    right = split_lines("\n".join(str(i) for i in range(1, 21)) + "\nDIFFERENT\n")
    rows, _, _ = generate_side_by_side(left, right, DiffOptions(collapse_unchanged=True))
    assert any(r.op == LineOp.CONTEXT_SKIP for r in rows)


def test_unified_diff_basic():
    left = ["a", "b", "c"]
    right = ["a", "x", "c"]
    result = generate_unified_diff(left, right, "left.txt", "right.txt")
    joined = "\n".join(result)
    assert "-b" in joined
    assert "+x" in joined
