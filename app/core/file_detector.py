"""Text vs. binary file detection.

We don't hard-code "only these extensions are text". Instead we use a fast
extension allow-list as a shortcut for the common cases, and fall back to a
content heuristic (a variant of the approach Git and Perl's -T use: sample
the first few KB, and treat the file as binary if it contains a NUL byte or
a high proportion of non-printable/non-UTF8 bytes).
"""

from __future__ import annotations

SAMPLE_SIZE = 8192

# Extensions we already know are text -- used only to skip the content sniff
# for the overwhelmingly common cases; anything not in this list still gets
# a fair chance via the content heuristic in `sniff_is_text`.
KNOWN_TEXT_EXTENSIONS = {
    "py", "js", "jsx", "ts", "tsx", "java", "go", "rs", "cpp", "cc", "cxx",
    "c", "h", "hpp", "html", "htm", "css", "scss", "sass", "less", "json",
    "yaml", "yml", "xml", "md", "markdown", "txt", "sql", "sh", "bash",
    "zsh", "env", "ini", "cfg", "conf", "toml", "csv", "tsv", "rb", "php",
    "pl", "swift", "kt", "kts", "scala", "r", "lua", "vue", "svelte",
    "gradle", "properties", "gitignore", "dockerfile", "makefile", "cmake",
    "bat", "ps1", "vim", "editorconfig", "graphql", "proto", "rst",
}

KNOWN_BINARY_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "webp", "bmp", "ico", "tiff", "pdf",
    "exe", "dll", "so", "dylib", "zip", "tar", "gz", "bz2", "xz", "7z",
    "rar", "mp3", "mp4", "mov", "avi", "mkv", "wav", "flac", "ogg",
    "woff", "woff2", "ttf", "otf", "eot", "class", "jar", "war", "pyc",
    "pyo", "o", "a", "lib", "bin", "db", "sqlite", "sqlite3", "iso",
}


def sniff_is_text(sample: bytes) -> bool:
    """Heuristically decide whether a byte sample looks like text."""
    if not sample:
        return True  # empty file: treat as text (nothing to diff either way)
    if b"\x00" in sample:
        return False

    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        pass

    # Not valid UTF-8: fall back to a printable-byte ratio heuristic so we
    # still handle other text encodings reasonably (e.g. legacy latin-1
    # files) without misclassifying genuinely binary data.
    text_bytes = bytes(range(0x20, 0x7F)) + b"\n\r\t\b\f"
    printable = sum(1 for b in sample if b in text_bytes or b >= 0x80)
    ratio = printable / len(sample)
    return ratio > 0.85


def is_text_path(rel_path: str, sample: bytes) -> bool:
    """Decide if a file is text, using extension as a fast-path hint."""
    ext = rel_path.rsplit("/", 1)[-1].rsplit(".", 1)[-1].lower() if "." in rel_path else ""
    if ext in KNOWN_TEXT_EXTENSIONS:
        return True
    if ext in KNOWN_BINARY_EXTENSIONS:
        return False
    return sniff_is_text(sample)


def read_sample(path: str, size: int = SAMPLE_SIZE) -> bytes:
    with open(path, "rb") as fh:
        return fh.read(size)
