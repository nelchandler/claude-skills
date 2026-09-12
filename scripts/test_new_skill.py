"""Tests for new_skill.py.

The scaffolder's job is catching mistakes that are otherwise invisible -- a
misspelled frontmatter key, a description past the cap, a directory name that
won't work as a command. So these tests check that it actually catches them,
and that the no-PyYAML fallback parser agrees with PyYAML rather than merely
running.

    python -m pytest test_new_skill.py -q
"""

from __future__ import annotations

import pytest

import new_skill
from new_skill import (
    DESCRIPTION_LIMIT,
    check,
    create,
    description_length,
    parse_frontmatter,
    split_frontmatter,
)


def write_skill(root, name, frontmatter: str, body: str = "\n# Body\n"):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n{body}")
    return d


GOOD_FM = (
    "name: good-skill\n"
    "description: >-\n"
    "  Does a specific thing worth doing.\n"
    "  Use this skill whenever the user asks about widgets, sprockets, or\n"
    "  anything that rattles. Use it too when you merely see a .widget file.\n"
)


# --------------------------------------------------------------------------- #
# Frontmatter parsing
# --------------------------------------------------------------------------- #

def test_split_frontmatter_requires_delimiters():
    assert split_frontmatter("---\nname: x\n---\nbody") is not None
    assert split_frontmatter("no frontmatter here") is None
    assert split_frontmatter("---\nname: x\n") is None  # unterminated


def test_parse_folded_description_is_joined_into_one_line():
    fm = parse_frontmatter(f"---\n{GOOD_FM}---\n")
    assert fm["name"] == "good-skill"
    assert "\n" not in fm["description"]
    assert fm["description"].startswith("Does a specific thing")
    assert fm["description"].endswith(".widget file.")


def test_fallback_parser_agrees_with_pyyaml(monkeypatch):
    """The fallback runs on machines without PyYAML -- it has to be equivalent."""
    text = f"---\n{GOOD_FM}---\n"
    if new_skill._yaml is None:
        pytest.skip("PyYAML not installed; nothing to compare against")
    with_yaml = parse_frontmatter(text)
    monkeypatch.setattr(new_skill, "_yaml", None)
    without_yaml = parse_frontmatter(text)
    assert with_yaml["name"] == without_yaml["name"]
    assert with_yaml["description"] == without_yaml["description"]


def test_fallback_parser_handles_plain_scalars_and_quotes(monkeypatch):
    monkeypatch.setattr(new_skill, "_yaml", None)
    fm = parse_frontmatter('---\nname: plain\ndescription: "quoted value"\nmodel: inherit\n---\n')
    assert fm == {"name": "plain", "description": "quoted value", "model": "inherit"}


def test_description_length_counts_when_to_use():
    fm = {"description": "a" * 100, "when_to_use": "b" * 50}
    assert description_length(fm) == 150


# --------------------------------------------------------------------------- #
# Creating
# --------------------------------------------------------------------------- #

def test_create_makes_a_skill_that_passes_check(tmp_path):
    create("my-skill", "Does a thing. Use this skill whenever a thing needs doing, and "
           "also when you see a thing-shaped file lying around in the repo.",
           False, False, skills_dir=tmp_path)
    assert (tmp_path / "my-skill" / "SKILL.md").exists()
    errors, _ = check(tmp_path)
    assert errors == []


def test_create_optional_directories(tmp_path):
    create("with-extras", None, True, True, skills_dir=tmp_path)
    assert (tmp_path / "with-extras" / "scripts").is_dir()
    assert (tmp_path / "with-extras" / "references").is_dir()
    create("without-extras", None, False, False, skills_dir=tmp_path)
    assert not (tmp_path / "without-extras" / "scripts").exists()


@pytest.mark.parametrize("bad", ["My-Skill", "my_skill", "my skill", "-leading",
                                 "trailing-", "double--hyphen", ""])
def test_create_rejects_names_that_would_not_work_as_commands(tmp_path, bad):
    with pytest.raises(SystemExit, match="kebab-case|not a valid"):
        create(bad, None, False, False, skills_dir=tmp_path)


def test_create_refuses_to_clobber_an_existing_skill(tmp_path):
    create("taken", None, False, False, skills_dir=tmp_path)
    with pytest.raises(SystemExit, match="already exists"):
        create("taken", None, False, False, skills_dir=tmp_path)


def test_create_rejects_an_over_cap_description(tmp_path):
    with pytest.raises(SystemExit, match="over the"):
        create("too-wordy", "x" * (DESCRIPTION_LIMIT + 1), False, False, skills_dir=tmp_path)


def test_template_placeholder_is_flagged_by_check(tmp_path):
    """A scaffolded-but-unedited skill should not pass silently."""
    create("unedited", None, False, False, skills_dir=tmp_path)
    _, warnings = check(tmp_path)
    assert any("placeholder" in w for w in warnings)


# --------------------------------------------------------------------------- #
# Checking
# --------------------------------------------------------------------------- #

def test_check_accepts_a_well_formed_skill(tmp_path):
    write_skill(tmp_path, "good-skill", GOOD_FM)
    errors, warnings = check(tmp_path)
    assert errors == []
    assert warnings == []


def test_check_errors_on_missing_skill_md(tmp_path):
    (tmp_path / "empty-dir").mkdir(parents=True)
    errors, _ = check(tmp_path)
    assert any("no SKILL.md" in e for e in errors)


def test_check_errors_on_missing_frontmatter(tmp_path):
    d = tmp_path / "bare"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("# Just a heading\n")
    errors, _ = check(tmp_path)
    assert any("no YAML frontmatter" in e for e in errors)


def test_check_errors_on_missing_description(tmp_path):
    write_skill(tmp_path, "nameless", "name: nameless\n")
    errors, _ = check(tmp_path)
    assert any("no description" in e for e in errors)


def test_check_errors_when_description_exceeds_the_cap(tmp_path):
    write_skill(tmp_path, "wordy", f"name: wordy\ndescription: {'x' * (DESCRIPTION_LIMIT + 10)}\n")
    errors, _ = check(tmp_path)
    assert any("over the" in e and "cap" in e for e in errors)


def test_check_counts_when_to_use_toward_the_cap(tmp_path):
    """Split across both fields, it still exceeds -- that is the whole point of the cap."""
    half = "x" * (DESCRIPTION_LIMIT // 2 + 50)
    write_skill(tmp_path, "split", f"name: split\ndescription: {half}\nwhen_to_use: {half}\n")
    errors, _ = check(tmp_path)
    assert any("over the" in e for e in errors)


def test_check_errors_on_non_kebab_directory(tmp_path):
    write_skill(tmp_path, "Bad_Name", GOOD_FM.replace("good-skill", "Bad_Name"))
    errors, _ = check(tmp_path)
    assert any("kebab-case" in e for e in errors)


def test_check_warns_on_name_directory_mismatch(tmp_path):
    write_skill(tmp_path, "actual-dir", GOOD_FM)  # name field says good-skill
    _, warnings = check(tmp_path)
    assert any("name field" in w for w in warnings)


def test_check_warns_on_misspelled_frontmatter_key(tmp_path):
    """A typo'd key is ignored silently by Claude Code, so it must be surfaced here."""
    write_skill(tmp_path, "typo", GOOD_FM.replace("name: good-skill", "name: typo") + "descripton: oops\n")
    _, warnings = check(tmp_path)
    assert any("unrecognised frontmatter key" in w for w in warnings)


def test_check_warns_on_a_bare_category_label(tmp_path):
    write_skill(tmp_path, "terse", "name: terse\ndescription: Simulation tools\n")
    _, warnings = check(tmp_path)
    assert any("category label" in w for w in warnings)
    assert any("when to use" in w for w in warnings)


def test_check_warns_near_the_cap(tmp_path):
    near = "Use this skill when " + "x" * int(DESCRIPTION_LIMIT * 0.92)
    write_skill(tmp_path, "nearly", f"name: nearly\ndescription: {near}\n")
    errors, warnings = check(tmp_path)
    assert errors == []
    assert any("near the cap" in w for w in warnings)


def test_check_reports_a_missing_skills_directory(tmp_path):
    errors, _ = check(tmp_path / "nonexistent")
    assert any("no skills/ directory" in e for e in errors)
