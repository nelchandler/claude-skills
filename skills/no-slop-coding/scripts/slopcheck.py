#!/usr/bin/env python3
"""Find the mechanical slop in a diff, or in a tree.

The judgement calls in a review -- is this abstraction premature, can this test
actually fail -- are not automatable, and this script does not try. It finds the
patterns that are decidable from the text, so the review pass can spend its
attention on the rest:

    python3 slopcheck.py --diff              # added lines vs HEAD, plus diff shape
    python3 slopcheck.py --diff main         # added lines vs another ref
    python3 slopcheck.py src/ tests/         # a whole tree

Findings exit 1; advisories (lower precision, worth a look) exit 0. Every check
is a prompt to look at a line, not a verdict on it. Standard library only.

One known false positive: a library's public function, called only by consumers
outside this repo, reports as a dead definition. List it in __all__ -- which is
where it belonged anyway -- and the check stays quiet.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

# Definitions referenced nowhere are only interesting if something could have
# referenced them, so the search corpus is every text file in the repo.
CODE_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".go", ".rs",
    ".java", ".kt", ".rb", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".swift",
    ".php", ".sh", ".bash", ".sql", ".scala", ".lua", ".pl", ".r",
}
TEXT_SUFFIXES = CODE_SUFFIXES | {
    ".md", ".rst", ".txt", ".toml", ".cfg", ".ini", ".yaml", ".yml", ".json",
}
SKIP_DIRS = {
    ".git", ".hg", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", "target", ".tox", ".mypy_cache", ".pytest_cache", ".idea",
}

# Filenames that are the residue of a change rather than part of the codebase.
SCAFFOLDING_RE = re.compile(
    r"(?:_v\d+|_new|_old|_final|_copy|_backup|_temp|_tmp|[ -]copy|\bcopy \d)"
    r"(?:\.[^.]+)?$|\.(?:bak|orig|rej|save)$|^(?:summary|notes|changes"
    r"|changes_made|implementation_notes|implementation|review|walkthrough"
    r"|refactor_summary|untitled)\.(?:md|txt)$",
    re.I,
)
COMPAT_RE = re.compile(
    r"back(?:ward|wards)?[\s-]*compat|backcompat|for compatibility"
    r"|kept for compat|legacy (?:shim|wrapper|alias|support|name|path)"
    r"|deprecated alias|old name|alias for",
    re.I,
)
DEBUGGER_RE = re.compile(r"\bdebugger;")     # non-Python; Python uses the AST
# Anchored: prose that mentions a TODO is not one.
TODO_RE = re.compile(r"^(?:TODO|FIXME|XXX|HACK)\b")
# A TODO is actionable if it names who or what: an owner, an issue, or a link.
TODO_OWNED_RE = re.compile(r"\(\s*[\w.@-]+\s*\)|#\d+|[A-Z]{2,}-\d+|https?://")
PRAGMA_RE = re.compile(
    r"type:\s*ignore|noqa|pylint:|pyright:|mypy:|pragma:|coding[:=]|!/|eslint"
    r"|prettier-ignore|fmt:\s*(?:on|off)|SPDX-",
    re.I,
)
NON_PYTHON_CODE_RE = re.compile(
    r"^\s*(?:return|if|for|while|function|const|let|var|import|console\.\w+\()\b"
    r".*[;{)]\s*$|^[\w.\[\]\"']+\s*=\s*[^=]")
NARRATION_RE = re.compile(
    r"^(?:step\s*\d+\b|now\b|then\b|next,|first,|finally,|initiali[sz]e\b"
    r"|declare\b|define\b|instantiate\b|create (?:the|a|an)\b|set (?:the|up)\b"
    r"|get (?:the|a|an)\b|return (?:the|a|an)\b|call (?:the|a|an)?\b"
    r"|loop (?:over|through)\b|iterate\b|increment\b|decrement\b|append\b"
    r"|check if\b|assign\b|import\b)",
    re.I,
)
STOPWORDS = {
    "the", "a", "an", "to", "of", "for", "in", "on", "and", "or", "is", "it",
    "this", "that", "each", "all", "if", "we", "then", "with", "from", "by",
    "into", "its", "our", "so", "as", "be", "at", "up",
}
# Names a caller may never mention: entry points, hooks, test bodies.
DEAD_DEF_EXEMPT = {"main", "setup", "teardown", "handler", "lambda_handler"}
DUPLICATE_WINDOW = 6
COMMENT_PREFIXES = ("#", "//")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    check: str
    message: str
    advisory: bool = False

    def format(self) -> str:
        return f"{self.path}:{self.line}  {self.check}  {self.message}"


# --------------------------------------------------------------------------- #
# Reading files
# --------------------------------------------------------------------------- #

def read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def walk(paths: list[Path]) -> list[Path]:
    """Expand paths to the text files under them, skipping vendored trees."""
    out: list[Path] = []
    for p in paths:
        if p.is_file():
            out.append(p)
            continue
        for child in sorted(p.rglob("*")):
            if not child.is_file() or child.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if SKIP_DIRS & set(child.parts):
                continue
            out.append(child)
    return out


def repo_root(start: Path) -> Path:
    """The git root above `start`, or `start` itself when there is no repo."""
    d = start if start.is_dir() else start.parent
    for candidate in [d, *d.parents]:
        if (candidate / ".git").exists():
            return candidate
    return d


def relative_to(path: Path, root: Path) -> str:
    """Repo-relative where the file is inside the repo, as given otherwise."""
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        return str(path)


def comment_body(line: str) -> str | None:
    """The text of a whole-line comment, or None if the line is not one."""
    stripped = line.strip()
    for prefix in COMMENT_PREFIXES:
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip()
    return None


# --------------------------------------------------------------------------- #
# Line-based checks (any language)
# --------------------------------------------------------------------------- #

def check_filename(rel: str) -> list[Finding]:
    name = Path(rel).name
    if SCAFFOLDING_RE.search(name):
        return [Finding(rel, 1, "scaffolding-file",
                        f"'{name}' names a change artifact, not part of the codebase "
                        "-- edit the original, and put change notes in the commit")]
    return []


def check_lines(rel: str, text: str) -> list[Finding]:
    out: list[Finding] = []
    lines = text.splitlines()
    is_python = rel.endswith((".py", ".pyi"))
    run: list[tuple[int, str]] = []          # consecutive comment lines

    for i, line in enumerate(lines, start=1):
        if not is_python and DEBUGGER_RE.search(line):
            out.append(Finding(rel, i, "debugger-statement",
                               "debugger statement left in committed code"))

        body = comment_body(line)
        if body is None:
            out.extend(_commented_out(rel, run, is_python))
            run = []
            continue
        if not PRAGMA_RE.search(body):
            run.append((i, body))

        if COMPAT_RE.search(body):
            out.append(Finding(rel, i, "compat-shim",
                               "keeps an old path alive alongside the new one; inside a "
                               "codebase you control, migrate the callers and delete it"))
        if TODO_RE.search(body) and not TODO_OWNED_RE.search(body):
            out.append(Finding(rel, i, "loose-todo",
                               "TODO with no owner, issue or link -- it will never be "
                               "actioned, so do it now or drop it", advisory=True))
        if narration := _narration(body, lines[i:]):
            out.append(Finding(rel, i, "narration-comment", narration, advisory=True))

    out.extend(_commented_out(rel, run, is_python))
    return out


def _narration(body: str, following: list[str]) -> str | None:
    """A comment that restates the code line under it."""
    words = [w for w in re.findall(r"[a-zA-Z_]+", body.lower()) if w not in STOPWORDS]
    if not 1 <= len(words) <= 8 or not NARRATION_RE.match(body):
        return None
    for line in following:
        if not line.strip() or comment_body(line) is not None:
            continue
        code = line.lower()
        if any(w in code for w in words):
            return f"restates the line below it ({line.strip()[:48]!r})"
        return None
    return None


def _commented_out(rel: str, run: list[tuple[int, str]],
                   is_python: bool) -> list[Finding]:
    """Commented-out code in a run of consecutive comment lines.

    For Python the test is whether the text parses as a real statement -- far
    more precise than pattern-matching, since English rarely parses. The run is
    tried whole and then line by line, because an indented block loses its
    context when the comment markers come off. Other languages get patterns.
    """
    if not run:
        return []
    bodies = [body for _, body in run]
    if is_python:
        looks_like_code = (_parses_as_code("\n".join(bodies))
                           or any(_parses_as_code(b) for b in bodies))
    else:
        looks_like_code = any(NON_PYTHON_CODE_RE.search(b) for b in bodies)
    if not looks_like_code:
        return []
    return [Finding(rel, run[0][0], "commented-out-code",
                    "dead code in a comment: no linting, no tests, and every reader "
                    "wonders whether it is the fallback -- delete it, git has it")]


def _parses_as_code(text: str) -> bool:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return False
    real = (ast.Assign, ast.AugAssign, ast.Return, ast.If, ast.For, ast.While,
            ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import,
            ast.ImportFrom, ast.Try, ast.With, ast.Raise, ast.Assert, ast.Delete)
    for node in tree.body:
        if isinstance(node, real):
            return True
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            return True
        # An annotated assignment only counts with a value: '# count: int = 0' is
        # commented-out code, while '# type: ignore' is an annotation on nothing.
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            return True
    return False


# --------------------------------------------------------------------------- #
# Python AST checks
# --------------------------------------------------------------------------- #

def check_python(rel: str, text: str, corpus: dict[str, int]) -> list[Finding]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    out = _swallowed_exceptions(rel, tree) + _debugger_calls(rel, tree)
    if Path(rel).name not in {"__init__.py", "conftest.py"}:
        out.extend(_dead_definitions(rel, tree, corpus))
    return out


def _debugger_calls(rel: str, tree: ast.AST) -> list[Finding]:
    out: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        called = (isinstance(func, ast.Name) and func.id == "breakpoint") or (
            isinstance(func, ast.Attribute) and func.attr == "set_trace")
        if called:
            out.append(Finding(rel, node.lineno, "debugger-statement",
                               "debugger call left in committed code"))
    return out


def _swallowed_exceptions(rel: str, tree: ast.AST) -> list[Finding]:
    out: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if any(isinstance(n, ast.Raise) for n in ast.walk(node)):
            continue
        broad = _is_broad(node.type)
        inert = (all(_is_inert(stmt) for stmt in node.body)
                 or _returns_constant(node.body[-1]))
        if broad and inert:
            out.append(Finding(
                rel, node.lineno, "swallowed-exception",
                "catches everything -- including the bugs in the try block -- and "
                "continues; catch the specific error you can handle, or let it raise"))
        elif len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
            out.append(Finding(
                rel, node.lineno, "ignored-exception",
                "discards the exception silently; if ignoring it is deliberate, say "
                "why in a comment", advisory=True))
    return out


def _is_broad(node: ast.expr | None) -> bool:
    if node is None:
        return True
    names = node.elts if isinstance(node, ast.Tuple) else [node]
    return any(isinstance(n, ast.Name) and n.id in {"Exception", "BaseException"}
               for n in names)


def _is_inert(stmt: ast.stmt) -> bool:
    """A handler statement that neither handles the failure nor reports it up."""
    if isinstance(stmt, (ast.Pass, ast.Continue, ast.Break)):
        return True
    if isinstance(stmt, ast.Expr):
        return isinstance(stmt.value, ast.Call)      # a log or print call
    return _returns_constant(stmt)


def _returns_constant(stmt: ast.stmt) -> bool:
    """`return None` / `return {}` / `return 0`: a default standing in for a failure."""
    if not isinstance(stmt, ast.Return):
        return False
    return stmt.value is None or isinstance(
        stmt.value, (ast.Constant, ast.List, ast.Dict, ast.Set, ast.Tuple))


def _dead_definitions(rel: str, tree: ast.Module,
                      corpus: dict[str, int]) -> list[Finding]:
    """Module-level definitions whose name appears nowhere else in the repo.

    Decorated definitions are skipped: a decorator can register a function that
    nothing ever names again.
    """
    exported: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            exported = {e.value for e in getattr(node.value, "elts", [])
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)}

    out: list[Finding] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        name = node.name
        if (node.decorator_list or name in exported or name in DEAD_DEF_EXEMPT
                or name.startswith(("test_", "__"))):
            continue
        if corpus.get(name, 0) <= 1:
            out.append(Finding(
                rel, node.lineno, "dead-definition",
                f"'{name}' is defined here and referenced nowhere else in the repo"))
    return out


def reference_counts(root: Path) -> dict[str, int]:
    """How often each identifier appears across the repo's text files."""
    counts: dict[str, int] = defaultdict(int)
    for path in walk([root]):
        text = read(path)
        if text is None:
            continue
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text):
            counts[token] += 1
    return counts


# --------------------------------------------------------------------------- #
# Duplication
# --------------------------------------------------------------------------- #

def check_duplicates(files: dict[str, str]) -> list[Finding]:
    """Blocks of identical code in two places among the scanned files."""
    seen: dict[str, tuple[str, int]] = {}
    out: list[Finding] = []
    last_end: dict[str, int] = {}

    for rel, text in files.items():
        if Path(rel).suffix.lower() not in CODE_SUFFIXES:
            continue
        significant = [
            (i, re.sub(r"\s+", " ", line.strip()))
            for i, line in enumerate(text.splitlines(), start=1)
            if len(line.strip()) >= 8 and comment_body(line) is None
        ]
        for start in range(len(significant) - DUPLICATE_WINDOW + 1):
            window = significant[start:start + DUPLICATE_WINDOW]
            key = "\n".join(norm for _, norm in window)
            first, line = window[0]
            if key not in seen:
                seen[key] = (rel, first)
                continue
            origin_path, origin_line = seen[key]
            if (origin_path, origin_line) == (rel, first):
                continue
            if first <= last_end.get(rel, 0):
                continue
            last_end[rel] = window[-1][0]
            out.append(Finding(
                rel, first, "duplicate-block",
                f"{DUPLICATE_WINDOW} identical lines also at "
                f"{origin_path}:{origin_line} -- consolidate rather than keeping both"))
    return out


# --------------------------------------------------------------------------- #
# Diff mode
# --------------------------------------------------------------------------- #

@dataclass
class Diff:
    added: dict[str, set[int]]     # path -> line numbers added
    removed: dict[str, int]        # path -> count of lines removed
    new_files: set[str]


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def parse_diff(patch: str) -> Diff:
    added: dict[str, set[int]] = defaultdict(set)
    removed: dict[str, int] = defaultdict(int)
    new_files: set[str] = set()
    path, lineno, pending_new = None, 0, False

    for line in patch.splitlines():
        if line.startswith("diff --git"):
            path, pending_new = None, False
        elif line.startswith("new file mode"):
            pending_new = True
        elif line.startswith("+++ "):
            target = line[4:].strip()
            path = None if target == "/dev/null" else target.removeprefix("b/")
            if path and pending_new:
                new_files.add(path)
        elif line.startswith("@@") and path:
            if m := re.search(r"\+(\d+)", line):
                lineno = int(m.group(1))
        elif path and line.startswith("+") and not line.startswith("+++"):
            added[path].add(lineno)
            lineno += 1
        elif path and line.startswith("-") and not line.startswith("---"):
            removed[path] += 1
    return Diff(dict(added), dict(removed), new_files)


def collect_diff(root: Path, ref: str) -> Diff:
    """Added lines against `ref`, counting untracked files as wholly added."""
    diff = parse_diff(git(root, "diff", "--unified=0", "--no-color", ref))
    for rel in git(root, "ls-files", "--others", "--exclude-standard").split():
        text = read(root / rel)
        if text is None or Path(rel).suffix.lower() not in TEXT_SUFFIXES:
            continue
        diff.added[rel] = set(range(1, len(text.splitlines()) + 1))
        diff.new_files.add(rel)
    return diff


def shape(root: Path, diff: Diff) -> list[str]:
    """Diff-shape numbers: the aggregate symptom a reviewer feels first."""
    added = sum(len(v) for v in diff.added.values())
    removed = sum(diff.removed.values())
    comment_lines = 0
    for rel, lines in diff.added.items():
        text = read(root / rel)
        if text is None:
            continue
        all_lines = text.splitlines()
        comment_lines += sum(
            1 for n in lines
            if n <= len(all_lines) and comment_body(all_lines[n - 1]) is not None)

    out = [f"{len(diff.added)} file(s) changed, {len(diff.new_files)} new; "
           f"+{added} -{removed} lines"]
    if added:
        out.append(f"{100 * comment_lines // added}% of added lines are comments")
    if diff.new_files:
        out.append("new files: " + ", ".join(sorted(diff.new_files))
                   + " -- could any of these have been an edit?")
    return out


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

def scan(files: dict[str, str], corpus: dict[str, int]) -> list[Finding]:
    out: list[Finding] = []
    for rel, text in files.items():
        out.extend(check_filename(rel))
        if Path(rel).suffix.lower() not in CODE_SUFFIXES:
            continue
        out.extend(check_lines(rel, text))
        if rel.endswith((".py", ".pyi")):
            out.extend(check_python(rel, text, corpus))
    out.extend(check_duplicates(files))
    return out


def run(paths: list[str], diff_ref: str | None) -> tuple[list[Finding], list[str]]:
    root = repo_root(Path(paths[0] if paths else ".").resolve())
    corpus = reference_counts(root)

    if diff_ref is not None:
        diff = collect_diff(root, diff_ref)
        files = {rel: text for rel in sorted(diff.added)
                 if (text := read(root / rel)) is not None}
        findings = [f for f in scan(files, corpus)
                    if f.line in diff.added.get(f.path, set())
                    or f.check == "scaffolding-file" and f.path in diff.new_files]
        return findings, shape(root, diff)

    files = {}
    for path in walk([Path(p) for p in paths]):
        text = read(path)
        if text is not None:
            files[relative_to(path, root)] = text
    return scan(files, corpus), []


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("paths", nargs="*", help="files or directories to scan")
    p.add_argument("--diff", nargs="?", const="HEAD", metavar="REF",
                   help="only lines added against REF (default HEAD), plus diff shape")
    args = p.parse_args(argv)
    if not args.paths and args.diff is None:
        p.error("give paths to scan, or --diff")

    findings, notes = run(args.paths or ["."], args.diff)
    blocking = sorted((f for f in findings if not f.advisory),
                      key=lambda f: (f.path, f.line))
    advisory = sorted((f for f in findings if f.advisory),
                      key=lambda f: (f.path, f.line))

    for f in blocking:
        print(f.format())
    if advisory:
        print("\nadvisory (lower precision, worth a look):")
        for f in advisory:
            print(f"  {f.format()}")
    if notes:
        print("\ndiff shape:")
        for note in notes:
            print(f"  {note}")

    print(f"\n{len(blocking)} finding(s), {len(advisory)} advisory.")
    if blocking:
        print("Each is a line to look at, not a verdict. Nothing here detects a "
              "one-caller wrapper or a test that cannot fail -- those are yours.")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
