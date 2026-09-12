#!/usr/bin/env python3
"""Scaffold a new skill, and check the ones already here.

Adding a skill to this repo is one directory, so the scaffolding is thin on
purpose. What the script is really for is the parts that are easy to get wrong
and invisible when you do: the frontmatter fields Claude actually reads, the
1,536-character description cap, and the fact that the *directory* name is what
makes /<skill-name> work while the `name:` field is only ever displayed.

    python3 scripts/new_skill.py my-new-skill
    python3 scripts/new_skill.py my-new-skill --description "..." --with-scripts
    python3 scripts/new_skill.py --check          # validate every skill here

--check exits non-zero on errors, so it works as a pre-commit or CI gate.
Depends only on the standard library; uses PyYAML for frontmatter when it is
installed and falls back to a small parser when it is not.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml as _yaml
except ImportError:  # pragma: no cover - exercised by the fallback test
    _yaml = None

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"

# Claude reads `description` (plus `when_to_use`) to decide whether to invoke a
# skill; the two share this budget. Over it, the tail is silently cut.
DESCRIPTION_LIMIT = 1536

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def display_path(path: Path) -> str:
    """Repo-relative where possible, absolute otherwise (tests use temp dirs)."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)

# Frontmatter keys Claude Code recognises. Anything else is very likely a typo,
# and a misspelled key fails silently rather than erroring.
KNOWN_KEYS = {
    "name", "description", "when_to_use", "argument-hint", "arguments",
    "disable-model-invocation", "user-invocable", "allowed-tools",
    "disallowed-tools", "model", "effort", "context", "agent", "background",
    "hooks", "paths", "shell", "metadata", "license", "compatibility",
}

TEMPLATE = '''---
name: {name}
description: >-
  {description}
---

# {title}

## What this does

<One paragraph on the job this skill does, and why it is worth doing that way.
Explain the reasoning rather than only the steps -- it travels further than a
list of rules, and lets the model handle cases you did not anticipate.>

## How to do it

1. <First step>
2. <Second step>

## Reference files

<Delete this section if the skill has none. Otherwise point at them and say when
each is worth reading, so they load on demand rather than all at once:>

| File | Read it when |
|---|---|
| `references/example.md` | <the situation that calls for it> |
'''

DESCRIPTION_PLACEHOLDER = (
    "<What this skill does, in one or two sentences.> "
    "Use this skill whenever <concrete situations, listed out>. "
    "Use it too when <indirect signals: symptoms, filenames, library names, "
    "things you might see in the code> even if the user never says the obvious "
    "keyword."
)


# --------------------------------------------------------------------------- #
# Frontmatter
# --------------------------------------------------------------------------- #

def split_frontmatter(text: str) -> str | None:
    """Return the raw YAML frontmatter block, or None if there isn't one."""
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    return parts[1] if len(parts) >= 3 else None


def parse_frontmatter(text: str) -> dict:
    """Parse SKILL.md frontmatter into a dict.

    Falls back to a minimal parser when PyYAML is absent, handling the shapes
    frontmatter actually uses: top-level scalars and folded/literal blocks. The
    fallback keeps nested values as raw text, which is enough for validation.
    """
    raw = split_frontmatter(text)
    if raw is None:
        return {}
    if _yaml is not None:
        loaded = _yaml.safe_load(raw)
        return loaded if isinstance(loaded, dict) else {}

    out: dict[str, str] = {}
    key, block, indent = None, [], None
    for line in raw.splitlines():
        if not line.strip():
            if key:
                block.append("")
            continue
        leading = len(line) - len(line.lstrip())
        if key and (indent is None or leading >= indent) and leading > 0:
            indent = leading if indent is None else indent
            block.append(line.strip())
            continue
        if key:
            out[key] = " ".join(b for b in block if b).strip()
            key, block, indent = None, [], None
        m = re.match(r"^([\w.-]+):\s*(.*)$", line)
        if not m:
            continue
        k, v = m.group(1), m.group(2).strip()
        if v in (">", ">-", "|", "|-", ""):
            key, block, indent = k, [], None
        else:
            out[k] = v.strip("'\"")
    if key:
        out[key] = " ".join(b for b in block if b).strip()
    return out


def description_length(fm: dict) -> int:
    """Characters counted against the cap: description plus when_to_use."""
    parts = [str(fm.get(k, "")) for k in ("description", "when_to_use")]
    return sum(len(p) for p in parts if p)


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #

def create(name: str, description: str | None, with_scripts: bool,
           with_references: bool, skills_dir: Path = SKILLS_DIR) -> Path:
    if not NAME_RE.match(name):
        raise SystemExit(
            f"'{name}' is not a valid skill name.\n"
            "Use kebab-case: lowercase letters and digits, single hyphens between "
            "words (e.g. 'simulation-engineer'). The directory name is what makes "
            f"/{name} work, so it has to be the name you want to type."
        )
    target = skills_dir / name
    if target.exists():
        raise SystemExit(f"{display_path(target)} already exists -- pick another name.")

    desc = description or DESCRIPTION_PLACEHOLDER
    if len(desc) > DESCRIPTION_LIMIT:
        raise SystemExit(
            f"description is {len(desc)} characters, over the {DESCRIPTION_LIMIT} cap. "
            "Trim it -- the tail would be cut silently."
        )
    title = name.replace("-", " ").title()

    target.mkdir(parents=True)
    (target / "SKILL.md").write_text(
        TEMPLATE.format(name=name, description=desc, title=title)
    )
    if with_references:
        (target / "references").mkdir()
        (target / "references" / ".gitkeep").write_text("")
    if with_scripts:
        (target / "scripts").mkdir()
        (target / "scripts" / ".gitkeep").write_text("")
    return target


# --------------------------------------------------------------------------- #
# Check
# --------------------------------------------------------------------------- #

def check(skills_dir: Path = SKILLS_DIR) -> tuple[list[str], list[str]]:
    """Validate every skill. Returns (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

    if not skills_dir.is_dir():
        return [f"no skills/ directory at {skills_dir}"], []

    dirs = sorted(d for d in skills_dir.iterdir() if d.is_dir())
    if not dirs:
        warnings.append("skills/ is empty")

    for d in dirs:
        rel = d.name
        skill_md = d / "SKILL.md"
        if not skill_md.exists():
            errors.append(f"{rel}: no SKILL.md (a skill directory without one is invisible)")
            continue
        if not NAME_RE.match(rel):
            errors.append(
                f"{rel}: directory name is not kebab-case; this is the invocable name"
            )

        text = skill_md.read_text()
        if split_frontmatter(text) is None:
            errors.append(f"{rel}: SKILL.md has no YAML frontmatter between --- markers")
            continue
        fm = parse_frontmatter(text)

        desc = str(fm.get("description", "")).strip()
        if not desc:
            errors.append(
                f"{rel}: no description -- this is what Claude reads to decide whether "
                "to invoke the skill, so without it the skill rarely fires"
            )
        else:
            n = description_length(fm)
            if n > DESCRIPTION_LIMIT:
                errors.append(
                    f"{rel}: description is {n} chars, over the {DESCRIPTION_LIMIT} cap "
                    "(description + when_to_use); the tail is cut silently"
                )
            elif n > DESCRIPTION_LIMIT * 0.9:
                warnings.append(f"{rel}: description is {n}/{DESCRIPTION_LIMIT} chars, near the cap")
            if "<" in desc and ">" in desc:
                warnings.append(f"{rel}: description still contains template placeholders")
            if not re.search(r"\buse (this|it)\b|\bwhen\b|\bwhenever\b", desc, re.I):
                warnings.append(
                    f"{rel}: description never says when to use the skill; "
                    "under-triggering is the usual failure mode"
                )
            if len(desc) < 80:
                warnings.append(
                    f"{rel}: description is only {len(desc)} chars -- a bare category "
                    "label gives Claude little to match against"
                )

        name_field = str(fm.get("name", "")).strip()
        if name_field and name_field != rel:
            warnings.append(
                f"{rel}: name field is '{name_field}' but the directory is '{rel}'. "
                "The directory wins for invocation; the mismatch just confuses readers"
            )

        unknown = set(fm) - KNOWN_KEYS
        if unknown:
            warnings.append(
                f"{rel}: unrecognised frontmatter key(s) {sorted(unknown)} -- "
                "a misspelled key is ignored silently"
            )

    return errors, warnings


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Scaffold a new skill, or check the existing ones.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("name", nargs="?", help="skill name in kebab-case")
    p.add_argument("--description", help="frontmatter description; a template is used if omitted")
    p.add_argument("--with-scripts", action="store_true", help="also create scripts/")
    p.add_argument("--with-references", action="store_true", help="also create references/")
    p.add_argument("--check", action="store_true", help="validate every skill and exit")
    args = p.parse_args(argv)

    if args.check:
        errors, warnings = check()
        for w in warnings:
            print(f"warning: {w}")
        for e in errors:
            print(f"ERROR:   {e}", file=sys.stderr)
        n = len([d for d in SKILLS_DIR.iterdir() if d.is_dir()]) if SKILLS_DIR.is_dir() else 0
        if errors:
            print(f"\n{len(errors)} error(s) across {n} skill(s).", file=sys.stderr)
            return 1
        print(f"\n{n} skill(s) OK" + (f", {len(warnings)} warning(s)." if warnings else "."))
        return 0

    if not args.name:
        p.error("give a skill name, or --check")

    target = create(args.name, args.description, args.with_scripts, args.with_references)
    rel = display_path(target)
    print(f"Created {rel}/SKILL.md")
    print()
    print("Next:")
    print(f"  1. Write the description in {rel}/SKILL.md -- it is the whole triggering")
    print("     mechanism, so list concrete situations, not a category label.")
    print("  2. Fill in the body.")
    print("  3. python3 scripts/new_skill.py --check")
    print("  4. Commit. No manifest edits needed; installed copies pick it up on")
    print("     /plugin marketplace update nelchandler")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
