from app.core.ignore_rules import IgnoreRules


def test_wildcard_extension():
    rules = IgnoreRules.from_text("*.pyc\n")
    assert rules.is_ignored("foo/bar.pyc")
    assert not rules.is_ignored("foo/bar.py")


def test_directory_pattern_anywhere():
    rules = IgnoreRules.from_text("node_modules/\n")
    assert rules.is_ignored("node_modules", is_dir=True)
    assert rules.is_ignored("frontend/node_modules", is_dir=True)
    assert rules.is_ignored("frontend/node_modules/lodash/index.js")


def test_anchored_pattern():
    rules = IgnoreRules.from_text("/README.md\n")
    assert rules.is_ignored("README.md")
    assert not rules.is_ignored("docs/README.md")


def test_log_files_anywhere():
    rules = IgnoreRules.from_text("*.log\n")
    assert rules.is_ignored("app.log")
    assert rules.is_ignored("logs/app.log")


def test_empty_rules_ignores_nothing():
    rules = IgnoreRules.from_text("")
    assert not rules.is_ignored("anything.txt")


def test_comments_and_blank_lines_skipped():
    rules = IgnoreRules.from_text("# comment\n\n*.log\n")
    assert rules.patterns == ["*.log"]
