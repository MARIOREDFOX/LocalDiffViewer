import os
import zipfile

import pytest

from app.archive.zip_handler import UnsafeZipError, is_zip_file, make_zip, safe_extract_zip


def test_make_and_extract_roundtrip(tmp_path):
    src = tmp_path / "src"
    (src / "a" / "b").mkdir(parents=True)
    (src / "a" / "b" / "file.txt").write_text("hello")
    (src / "top.txt").write_text("world")

    zip_path = str(tmp_path / "out.zip")
    make_zip(str(src), zip_path)
    assert is_zip_file(zip_path)

    dest = str(tmp_path / "extracted")
    safe_extract_zip(zip_path, dest)

    assert (tmp_path / "extracted" / "top.txt").read_text() == "world"
    assert (tmp_path / "extracted" / "a" / "b" / "file.txt").read_text() == "hello"


def test_nested_directories_and_empty_dirs(tmp_path):
    zip_path = str(tmp_path / "nested.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("a/b/c/d.txt", "deep")
        zf.writestr("empty_dir/", "")

    dest = str(tmp_path / "out")
    safe_extract_zip(zip_path, dest)
    assert os.path.isfile(os.path.join(dest, "a", "b", "c", "d.txt"))
    assert os.path.isdir(os.path.join(dest, "empty_dir"))


def test_zip_slip_path_traversal_blocked(tmp_path):
    zip_path = str(tmp_path / "evil.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../../../etc/evil.txt", "pwned")

    dest = str(tmp_path / "out")
    with pytest.raises(UnsafeZipError):
        safe_extract_zip(zip_path, dest)


def test_zip_slip_absolute_path_neutralized(tmp_path):
    """A member with a leading '/' must NOT be written to the real /etc --
    it should be re-rooted safely inside the destination directory instead
    (the leading slash is stripped, matching how e.g. `tar` and most safe
    unzip tools behave)."""
    zip_path = str(tmp_path / "evil2.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("/etc/evil.txt", "pwned")

    dest = str(tmp_path / "out2")
    safe_extract_zip(zip_path, dest)

    assert os.path.isfile(os.path.join(dest, "etc", "evil.txt"))
    assert not os.path.exists("/etc/evil.txt")


def test_unicode_filenames_in_zip(tmp_path):
    zip_path = str(tmp_path / "uni.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("résumé 文件.txt", "hello")

    dest = str(tmp_path / "out3")
    safe_extract_zip(zip_path, dest)
    assert os.path.isfile(os.path.join(dest, "résumé 文件.txt"))
