---
name: no-slop-coding
description: >-
  Writes and reviews code a senior engineer would sign off on, and strips the filler that
  makes AI-written diffs recognisable: speculative abstractions, wrappers with one caller,
  try/except that swallows errors, comments restating the code, duplicated helpers,
  backward-compat shims nobody asked for, tests that cannot fail, summary files. Use
  whenever you are about to write, refactor or review code, and again before committing or
  opening a PR. Use it when the user says slop, bloat, over-engineered, verbose, defensive,
  clean this up, make it idiomatic, write it like a senior engineer, or asks for a review of
  a diff. Use it too when you only see the symptoms — a diff adding files instead of editing
  them, `utils.py` growing, `except Exception: pass`, docstrings echoing the signature,
  `_v2` names, commented-out code, emoji in log lines, a 400-line diff for a 20-line change
  — even if nobody says the word slop.
---

# No-Slop Coding

## What this does

Slop is code that looks like the right answer without being it: it compiles, it reads
fluently, it has docstrings and error handling and tests, and almost none of it is load
bearing. It is the characteristic failure of generated code, because generation is
rewarded for *plausibility* and plausibility is cheap — an extra abstraction layer, a
`try/except` around everything, a comment above every line, a `utils.py` helper used once.
Each addition looks like diligence in isolation. Together they are the reason a 20-line
change arrives as a 400-line diff that the reviewer cannot hold in their head.

This skill is a bias correction, not a style guide. The default pull is toward *adding*:
another guard, another wrapper, another file, another "just in case" branch. So the rule is
that every line must earn its place, and the working question for any line you are about to
write is not "could this help?" but **"what breaks if I delete it?"** If the answer is
nothing, it is slop — delete it before anyone has to read it.

Two things this is not. It is not code golf: clarity always wins over brevity, and the
places where verbosity is *correct* are listed below. And it is not a licence to
under-deliver — cutting requested scope to keep a diff small is its own failure, worse than
slop, because the work is now incomplete and nobody was told.

## The core test

Before you submit any diff, answer these three. They catch most of it:

1. **Does every line earn its place?** Delete anything whose absence changes no behaviour
   and teaches the reader nothing.
2. **Is this the smallest change that does the whole job?** Smallest *surface*, not
   smallest effort — and the whole job, not the easy part of it.
3. **Would a senior engineer on this team have written it this way?** If the diff would get
   "why is this here?" on five lines, remove those five lines first.

## Hard rules

### Scope and structure

1. **Edit the existing file.** Do not add `thing_v2.py`, `thing_new.py`, `enhanced_thing.py`
   or a parallel implementation beside the one you were asked to change. Two versions of
   one thing is the most expensive form of slop: every future reader has to work out which
   one runs.
2. **No speculative generality.** No parameter, config flag, hook, base class, interface,
   registry or strategy object whose only caller is the one you just wrote. Build the
   general case when the second caller exists, not in anticipation of it. "Easy to extend
   later" is what extracting an abstraction costs — it is cheap; guessing wrong is not.
3. **No wrapper with one caller.** A function that forwards its arguments unchanged is a
   name, not an abstraction. Inline it unless it hides something genuinely ugly or gives a
   test a seam it needs.
4. **One way to do a thing.** Delete the old path instead of keeping it alongside the new
   one. No compat aliases, no `use_new_impl=False` default, no deprecation shim — unless
   the code is a published API with callers you cannot see or the repo's own convention
   says otherwise. Inside a codebase you control, "keep both for safety" means shipping
   two behaviours and testing one.
5. **Reuse before you write.** Search the repo for the helper before adding it; check the
   stdlib and the dependencies already installed before either. Do not add a dependency for
   what 10 lines of stdlib does, and do not hand-roll what a dependency already does well.
6. **Match the surrounding code.** Its naming, error handling, logging, imports, test
   style and level of abstraction. Local consistency beats your preference, and a diff that
   reads like the file it is in is a diff that gets reviewed on its merits.

### Errors

7. **Let errors surface.** Never `except Exception: pass`. Never return `None`, `{}`, `[]`
   or a default on failure so the caller can keep going in an unknown state. Catch only the
   specific exception you can actually do something about, at the layer that can do it;
   everything else propagates to where it will be seen. Swallowed errors do not make code
   robust, they make failures silent and undebuggable — and silent wrong answers are worse
   than crashes.
8. **No defensive checks for impossible states.** Validate at the boundary — user input,
   network responses, file contents, public API arguments — then trust your own invariants
   inside. Re-checking for `None` three layers deep, where `None` cannot arrive, adds a
   branch nobody has ever executed and a reviewer cannot dismiss.
9. **Error messages carry the context.** Say what failed, with the value or path involved,
   and what the caller can do about it. This is verbosity that pays.

### Comments, docs, names

10. **Comments explain why, never what.** Delete narration — `# increment the counter`,
    `# Step 3: build the response`, `# loop over the items`. Keep the comment that records
    a non-obvious reason: an invariant, a workaround with a link, why the obvious approach
    fails, a unit or bound that is not in the type.
11. **No docstring that restates the signature.** If it names the parameters and their
    types and says nothing else, it is worse than nothing: it adds lines and goes stale.
    Write a docstring when there is a contract to state — units, ownership, raised errors,
    edge-case behaviour.
12. **Names say what the thing is.** No `data`, `result`, `info`, `helper`, `handle`,
    `process`, `manager` where a specific word exists. No new `utils.py` dumping ground; put
    the function next to what it serves.
13. **No leftovers.** No commented-out code, no `breakpoint()` or stray debug prints, no
    `TODO` without an owner and a concrete next step, no emoji or decorative banners in
    code or log lines, no `SUMMARY.md` / `NOTES.md` / `IMPLEMENTATION.md` written to explain
    a change — that belongs in the commit message and the PR body.

### Tests

14. **A test that cannot fail is worse than no test.** It costs runtime and buys false
    confidence. Before keeping a test, break the code deliberately and confirm it goes red.
15. **Assert on behaviour, not on the implementation.** Check returned values and observable
    effects. `assert mock.called` and "it did not raise" pass for code that computes the
    wrong answer, and over-mocked tests fail on every honest refactor.
16. **Test what would plausibly break** — the boundary, the empty input, the error path, the
    case in the bug report. Not a happy-path case per function for coverage's sake.

### Reporting

17. **Say what you actually did.** Report the tests you ran and their real output. If
    something is unverified, untested or left out, say so explicitly and say why. A
    confident summary of work you did not verify is the one slop that survives review,
    because nobody can see it in the diff.

## When verbosity is correct

Over-correcting into terseness is its own failure. Spend the lines here:

- **Error messages and log lines** that a person will read at 3am — the more context the
  better.
- **Public API docstrings** — the contract, units, raised exceptions, ownership.
- **The comment that explains why**, especially for a workaround, a non-obvious algorithm
  choice, or a deliberate deviation from the surrounding pattern.
- **Test names** — a long descriptive name is documentation of the behaviour under test.
- **Input validation at a trust boundary** — security-relevant checks are never speculative.
- **An explicit intermediate variable** that gives a name to a confusing expression.

## Before you submit: the subtraction pass

Reread your own diff once, adversarially, and try to delete each thing in it. This pass is
the whole skill; the rules above only tell you what to look for.

```
[ ] Read the diff as a reviewer, not as its author.
[ ] For each added line: what breaks if this goes? Nothing -> delete it.
[ ] Any new file that could have been an edit to an existing one?
[ ] Any abstraction, parameter or flag with exactly one caller?
[ ] Any except clause that hides a failure instead of handling it?
[ ] Any comment restating its line, or docstring restating its signature?
[ ] Any block duplicated from elsewhere in the repo?
[ ] Any old path left alive beside the new one?
[ ] Any test that would still pass if the change were reverted?
[ ] Does it match the file's existing idiom?
[ ] Is the whole requested job done, with anything skipped stated plainly?
```

Then run the repo's own checks — lint, format, typecheck, the tests for what you touched —
and report their real output.

## Bundled tooling

`scripts/slopcheck.py` finds the mechanical cases so the review pass can spend its attention
on judgement. It reports only patterns with a low false-positive rate, and it is a prompt to
look, not a verdict:

```bash
python3 scripts/slopcheck.py --diff              # added lines vs the merge-base, plus diff shape
python3 scripts/slopcheck.py src/ tests/         # whole tree
```

Findings (exit code 1): swallowed exceptions, module-level definitions referenced nowhere
else, backward-compat shims, duplicated blocks, commented-out code, debugger statements,
scaffolding filenames. Advisories (exit code 0): comments that restate their line, `TODO`
without an owner. Standard library only.

A clean run is not a clean diff — nothing here detects a wrapper with one caller or a test
that cannot fail. Those are yours.

## Reference files

Read the one matching what you are doing rather than all of them.

| File | Read it when |
|---|---|
| `references/slop-catalog.md` | You want the pattern-by-pattern list with before/after diffs |
| `references/comments-docs-naming.md` | Writing or cutting comments, docstrings, names |
| `references/errors-and-tests.md` | Error handling, defensive code, judging whether a test is real |
| `references/review-pass.md` | Reviewing a diff (yours or someone else's), or responding to review feedback |
| `scripts/slopcheck.py` | Before submitting any diff, as the mechanical half of the review pass |

## Related skills

- `continuous-improvement` — when the same slop keeps arriving. A recurring review finding
  is a process defect, not a code defect: DMAIC will measure the rate, prove which stage
  lets it through, and put a control in place (a lint rule, a CI gate, a template) so the
  fix holds. Reach for it once you are fixing the same class of thing for the third time,
  rather than fixing instance three.
- `simulation-engineer` — when the code under review is a simulation or statistical model.
  The rules here catch the shape of the code but say nothing about whether the numbers mean
  anything; an unvalidated model with a tidy diff is still the more dangerous artifact.
