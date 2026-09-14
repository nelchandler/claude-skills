"""Tests for slopcheck.py.

A slop detector that fires on good code is worse than none: people stop reading
its output, and the one real finding goes with the noise. So these tests are
mostly negative -- the correct version of each pattern must stay silent -- and
each check is pinned by both a hit and a near-miss.

    python -m pytest test_slopcheck.py -q
"""

from __future__ import annotations

import subprocess

import pytest

from slopcheck import (
    check_duplicates,
    check_filename,
    check_lines,
    check_python,
    main,
    parse_diff,
    reference_counts,
    run,
    scan,
    shape,
)


def checks(findings, *, advisory=None):
    """Check names in the findings, optionally filtered by advisory status."""
    return [f.check for f in findings
            if advisory is None or f.advisory is advisory]


def py(text, *, path="mod.py", corpus=None):
    """Run the Python checks over a snippet, with every name assumed referenced."""
    names = {tok: 9 for tok in text.replace("(", " ").replace(":", " ").split()}
    return check_python(path, text, corpus if corpus is not None else names)


# --------------------------------------------------------------------------- #
# Swallowed exceptions
# --------------------------------------------------------------------------- #

def test_broad_except_returning_default_is_a_finding():
    findings = py("""
try:
    x = load()
except Exception:
    x = None
    return {}
""")
    assert checks(findings) == ["swallowed-exception"]


def test_bare_except_with_pass_is_a_finding():
    assert "swallowed-exception" in checks(py("try:\n    f()\nexcept:\n    pass\n"))


def test_broad_except_that_logs_and_continues_is_a_finding():
    findings = py("""
try:
    f()
except Exception as e:
    log.error("failed: %s", e)
""")
    assert checks(findings) == ["swallowed-exception"]


def test_broad_except_that_reraises_is_not_a_finding():
    findings = py("""
try:
    f()
except Exception as e:
    log.error("failed")
    raise
""")
    assert findings == []


def test_broad_except_wrapping_the_cause_is_not_a_finding():
    findings = py("""
try:
    f()
except Exception as e:
    raise Failed("could not f()") from e
""")
    assert findings == []


def test_specific_except_with_documented_fallback_is_not_a_finding():
    findings = py("""
try:
    return read(path)
except FileNotFoundError:
    return DEFAULTS
""")
    assert findings == []


def test_specific_except_with_pass_is_only_advisory():
    findings = py("try:\n    f()\nexcept KeyError:\n    pass\n")
    assert checks(findings, advisory=True) == ["ignored-exception"]
    assert checks(findings, advisory=False) == []


def test_broad_except_that_does_real_work_is_not_a_finding():
    findings = py("""
try:
    return fast_path(x)
except Exception:
    metrics.incr("fallback")
    cleanup(x)
    result = slow_path(x)
    return result
""")
    assert findings == []


# --------------------------------------------------------------------------- #
# Dead definitions
# --------------------------------------------------------------------------- #

def test_definition_referenced_nowhere_else_is_a_finding():
    findings = py("def unused_helper(x):\n    return x\n",
                  corpus={"unused_helper": 1})
    assert checks(findings) == ["dead-definition"]


def test_definition_with_a_caller_is_not_a_finding():
    findings = py("def helper(x):\n    return x\n", corpus={"helper": 4})
    assert findings == []


def test_decorated_definition_is_skipped():
    findings = py("@app.route('/')\ndef index():\n    return 'hi'\n",
                  corpus={"index": 1})
    assert findings == []


def test_exported_definition_is_skipped():
    findings = py("__all__ = ['api']\n\ndef api(x):\n    return x\n",
                  corpus={"api": 1, "__all__": 1})
    assert findings == []


def test_test_functions_and_main_are_skipped():
    findings = py("def test_thing():\n    pass\n\ndef main():\n    pass\n",
                  corpus={"test_thing": 1, "main": 1})
    assert findings == []


def test_nested_function_is_not_reported():
    findings = py("def outer():\n    def inner():\n        pass\n    return inner\n",
                  corpus={"outer": 3, "inner": 2})
    assert findings == []


def test_init_and_conftest_are_exempt():
    src = "def reexported(x):\n    return x\n"
    assert py(src, path="pkg/__init__.py", corpus={"reexported": 1}) == []
    assert py(src, path="tests/conftest.py", corpus={"reexported": 1}) == []


# --------------------------------------------------------------------------- #
# Debugger statements
# --------------------------------------------------------------------------- #

def test_breakpoint_call_is_a_finding():
    assert checks(py("def f():\n    breakpoint()\n")) == ["debugger-statement"]


def test_set_trace_is_a_finding():
    assert checks(py("import pdb\n\ndef f():\n    pdb.set_trace()\n")) == [
        "debugger-statement"]


def test_breakpoint_inside_a_string_is_not_a_finding():
    """The detector's own source mentions these patterns; so do docs and tests."""
    findings = py('PATTERN = "breakpoint() and pdb.set_trace()"\n',
                  corpus={"PATTERN": 3})
    assert findings == []
    assert check_lines("mod.py", 'P = "debugger;"\n') == []


def test_debugger_statement_in_javascript_is_a_finding():
    assert checks(check_lines("app.js", "function f() {\n  debugger;\n}\n")) == [
        "debugger-statement"]


# --------------------------------------------------------------------------- #
# Commented-out code
# --------------------------------------------------------------------------- #

def test_commented_out_call_is_a_finding():
    text = "# result = old_method(x)\nresult = new_method(x)\n"
    assert checks(check_lines("mod.py", text)) == ["commented-out-code"]


def test_commented_out_indented_block_is_a_finding():
    text = "def f(x):\n    # if x:\n    #     return 1\n    return 2\n"
    assert "commented-out-code" in checks(check_lines("mod.py", text))


def test_english_comments_are_not_commented_out_code():
    text = (
        "# The vendor returns 200 with an error body, so the status is not enough.\n"
        "# See incident 4412.\n"
        "if 'error' in payload:\n"
        "    raise VendorError\n"
    )
    assert check_lines("mod.py", text) == []


def test_commented_out_annotated_assignment_is_a_finding():
    text = "# count: int = 0\ncount = start\n"
    assert checks(check_lines("mod.py", text)) == ["commented-out-code"]


@pytest.mark.parametrize("pragma", [
    "# type: ignore",
    "# noqa: E501",
    "# pylint: disable=invalid-name",
    "# mypy: disable-error-code=misc",
    "# fmt: off",
])
def test_pragma_comments_are_ignored(pragma):
    """Several pragmas parse as annotated assignments, so they need excluding."""
    assert check_lines("mod.py", pragma + "\nx = 1\n") == []


def test_commented_out_javascript_is_a_finding():
    text = "// const old = fetch(url);\nconst next = fetch(url);\n"
    assert "commented-out-code" in checks(check_lines("app.js", text))


# --------------------------------------------------------------------------- #
# Compat shims, narration, TODOs
# --------------------------------------------------------------------------- #

def test_compat_alias_comment_is_a_finding():
    text = "# Backwards compatibility\ncalculate_total = compute_total\n"
    assert "compat-shim" in checks(check_lines("mod.py", text))


def test_legacy_wrapper_comment_is_a_finding():
    text = "# legacy shim, kept until callers migrate\ndef old_api(x):\n    return x\n"
    assert "compat-shim" in checks(check_lines("mod.py", text))


def test_ordinary_comment_is_not_a_compat_shim():
    text = "# Sorted by arrival because the scheduler assumes FIFO.\nq.sort()\n"
    assert check_lines("mod.py", text) == []


def test_narration_comment_is_advisory():
    text = "# Loop over the items\nfor item in items:\n    pass\n"
    assert checks(check_lines("mod.py", text), advisory=True) == ["narration-comment"]
    assert checks(check_lines("mod.py", text), advisory=False) == []


def test_narration_needs_a_word_in_common_with_the_code():
    text = "# Now the slow path: the index is gone, so this rebuilds it.\nfoo(bar)\n"
    assert check_lines("mod.py", text) == []


def test_why_comment_is_not_narration():
    text = "# Timeout is 35s so the upstream error surfaces first.\nTIMEOUT = 35\n"
    assert check_lines("mod.py", text) == []


def test_unowned_todo_is_advisory():
    findings = check_lines("mod.py", "# TODO: make this faster\nx = 1\n")
    assert checks(findings, advisory=True) == ["loose-todo"]


@pytest.mark.parametrize("comment", [
    "# TODO(alice): drop after the migration",
    "# TODO: remove with #412",
    "# FIXME: blocked on PROJ-88",
    "# TODO: see https://example.com/issues/3",
])
def test_actionable_todo_is_not_flagged(comment):
    assert check_lines("mod.py", comment + "\nx = 1\n") == []


def test_prose_mentioning_todo_is_not_flagged():
    text = "# A TODO is actionable only when it names an owner.\nx = 1\n"
    assert check_lines("mod.py", text) == []


# --------------------------------------------------------------------------- #
# Filenames and duplication
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("path", [
    "src/parser_v2.py", "src/parser_new.py", "src/config_old.py",
    "src/mod.py.bak", "SUMMARY.md", "docs/IMPLEMENTATION_NOTES.md",
])
def test_scaffolding_filenames_are_findings(path):
    assert checks(check_filename(path)) == ["scaffolding-file"]


@pytest.mark.parametrize("path", [
    "src/parser.py", "src/v2/api.py", "README.md", "docs/architecture.md",
    "src/old_english_tokenizer.py",
])
def test_ordinary_filenames_are_not_findings(path):
    assert check_filename(path) == []


def test_identical_block_in_two_files_is_a_finding():
    block = "\n".join(f"    value_{i} = compute_something({i})" for i in range(8))
    findings = check_duplicates({"a.py": block, "b.py": block})
    assert checks(findings) == ["duplicate-block"]
    assert "a.py:1" in findings[0].message


def test_short_or_distinct_blocks_are_not_findings():
    short = "    x = compute(1)\n    y = compute(2)\n"
    assert check_duplicates({"a.py": short, "b.py": short}) == []
    a = "\n".join(f"    value_{i} = compute_a({i})" for i in range(8))
    b = "\n".join(f"    value_{i} = compute_b({i})" for i in range(8))
    assert check_duplicates({"a.py": a, "b.py": b}) == []


def test_duplicate_check_ignores_prose_files():
    block = "\n".join(f"a sentence about the thing number {i}" for i in range(8))
    assert check_duplicates({"a.md": block, "b.md": block}) == []


def test_prose_files_get_only_the_filename_check():
    """A document describing a pattern is not an instance of it."""
    doc = "Never write `except Exception: pass`.\n\n    # x = old_call()\n"
    assert scan({"docs/slop.md": doc}, {}) == []
    assert checks(scan({"SUMMARY.md": doc}, {})) == ["scaffolding-file"]


# --------------------------------------------------------------------------- #
# Diff parsing and shape
# --------------------------------------------------------------------------- #

PATCH = """diff --git a/src/mod.py b/src/mod.py
--- a/src/mod.py
+++ b/src/mod.py
@@ -3,0 +4,2 @@ def f():
+    added_one = 1
+    added_two = 2
@@ -10 +11,0 @@ def g():
-    gone = 1
diff --git a/src/new.py b/src/new.py
new file mode 100644
--- /dev/null
+++ b/src/new.py
@@ -0,0 +1,1 @@
+brand_new = 1
"""


def test_parse_diff_reads_added_line_numbers():
    diff = parse_diff(PATCH)
    assert diff.added["src/mod.py"] == {4, 5}
    assert diff.added["src/new.py"] == {1}
    assert diff.removed["src/mod.py"] == 1
    assert diff.new_files == {"src/new.py"}


def test_parse_diff_ignores_deleted_files():
    patch = ("diff --git a/gone.py b/gone.py\n--- a/gone.py\n+++ /dev/null\n"
             "@@ -1 +0,0 @@\n-x = 1\n")
    diff = parse_diff(patch)
    assert diff.added == {}
    assert diff.removed == {}


def test_shape_reports_counts_and_new_files(tmp_path):
    (tmp_path / "mod.py").write_text("# a comment\nx = 1\n")
    diff = parse_diff("--- a/mod.py\n+++ b/mod.py\n@@ -0,0 +1,2 @@\n+# a comment\n+x = 1\n")
    notes = shape(tmp_path, diff)
    assert "1 file(s) changed, 0 new; +2 -0 lines" in notes[0]
    assert "50% of added lines are comments" in notes[1]


# --------------------------------------------------------------------------- #
# End to end, against a real repository
# --------------------------------------------------------------------------- #

def git_repo(tmp_path):
    def run_git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True,
                       capture_output=True)
    run_git("init", "-q")
    run_git("config", "user.email", "t@example.com")
    run_git("config", "user.name", "t")
    return run_git


def test_diff_mode_reports_added_lines_only(tmp_path):
    run_git = git_repo(tmp_path)
    committed = tmp_path / "old.py"
    committed.write_text("__all__ = ['existing']\n\ndef existing():\n"
                         "    try:\n        f()\n"
                         "    except Exception:\n        pass\n")
    run_git("add", "-A")
    run_git("commit", "-qm", "initial")

    committed.write_text(committed.read_text()
                         + "    try:\n        g()\n"
                           "    except Exception:\n        return None\n")
    findings, notes = run([str(tmp_path)], "HEAD")

    assert checks(findings) == ["swallowed-exception"]
    assert findings[0].line == 10         # the new handler, not the committed one
    assert any("+4 -0 lines" in n for n in notes)


def test_diff_mode_includes_untracked_files(tmp_path):
    run_git = git_repo(tmp_path)
    (tmp_path / "keep.py").write_text("x = 1\n")
    run_git("add", "-A")
    run_git("commit", "-qm", "initial")
    (tmp_path / "parser_v2.py").write_text("def main():\n    breakpoint()\n")

    findings, notes = run([str(tmp_path)], "HEAD")

    assert sorted(checks(findings)) == ["debugger-statement", "scaffolding-file"]
    assert any("parser_v2.py" in n for n in notes)


def test_reference_counts_spans_the_repo(tmp_path):
    (tmp_path / "a.py").write_text("def shared():\n    return 1\n")
    (tmp_path / "b.py").write_text("from a import shared\nshared()\n")
    (tmp_path / "junk").mkdir()
    counts = reference_counts(tmp_path)
    assert counts["shared"] == 3
    assert counts["never_written"] == 0


def test_main_exits_nonzero_only_on_findings(tmp_path, capsys):
    clean = tmp_path / "clean.py"
    clean.write_text("__all__ = ['add']\n\n\ndef add(a, b):\n    return a + b\n")
    assert main([str(clean)]) == 0
    assert "0 finding(s)" in capsys.readouterr().out

    slop = tmp_path / "slop.py"
    slop.write_text("__all__ = ['add']\n\n\ndef add(a, b):\n    try:\n"
                    "        return a + b\n    except Exception:\n        return 0\n")
    assert main([str(slop)]) == 1
    assert "swallowed-exception" in capsys.readouterr().out


def test_main_requires_a_target():
    with pytest.raises(SystemExit):
        main([])


def test_unparseable_and_unreadable_files_do_not_crash(tmp_path):
    (tmp_path / "broken.py").write_text("def f(:\n")
    (tmp_path / "data.json").write_text('{"a": 1}')
    findings, _ = run([str(tmp_path)], None)
    assert findings == []
