# The review pass

How to read a diff — your own before submitting it, or someone else's — and what to do with
what you find.

## Reading your own diff

Read it top to bottom as the reviewer would, with no memory of writing it. The order matters:
structure first, because a file that should not exist makes its contents moot.

### 1. Shape

```bash
git diff --stat <base>
```

- Is the line count proportional to the change described? A 20-line behaviour change
  arriving as 400 lines means something else came along.
- Any **new file**? Justify each one. Could it have been an edit?
- Any file with a suspicious name — `*_v2`, `*_new`, `*_final`, `utils.py`, `SUMMARY.md`?
- Are unrelated changes mixed in (a reformat, a rename, a drive-by fix)? Split them out;
  they hide the real change.
- Did a lockfile, a build artifact, a `.env`, a log or a large binary get committed?

### 2. Structure

- Each new abstraction: how many callers *today*? One means inline it.
- Each new parameter or flag: is any call site passing a non-default value?
- Each new function: does one already exist in this repo, the stdlib, or a dependency?
  Grep the name, and grep the body's distinctive call.
- Is the old path deleted, or still alive beside the new one?

### 3. Line by line

For every added line: **what breaks if this goes?** Nothing → delete. Specifically:

- `except` clauses — does each handle a specific failure, or hide it?
- Null/type/range checks — can that state actually arrive here?
- Comments — does each say *why*? Delete the narration.
- Docstrings — anything beyond the signature?
- Names — `data`, `helper`, `process`, `manager`?
- Leftovers — commented-out code, `breakpoint()`, debug prints, emoji, `TODO` without an
  owner.

### 4. Tests

- Would each new test fail if the change were reverted? Check the important one by actually
  reverting it.
- Do the assertions check values, or only that something was called?
- Is the error path tested, and the boundary?
- Did any existing test get weakened, skipped or deleted to make the suite pass?

### 5. Truth

- Run the repo's own checks — lint, format, typecheck, the tests covering what you touched.
- Report their **real** output. Not "tests pass" from memory.
- State what you did not do: skipped scope, unverified paths, assumptions made. This is the
  only defect a reviewer cannot see in the diff, which is exactly why it has to be said.

## Reviewing someone else's diff

Same passes, different output. Severity, so the author knows what blocks:

| Level | Meaning | Examples |
|---|---|---|
| **Blocking** | Wrong behaviour, or a cost the codebase keeps paying | Swallowed error, wrong logic, a test that cannot fail, a parallel implementation, unbounded loop over a remote call, a security hole |
| **Should fix** | Real slop, cheap to remove now | One-caller wrapper, speculative interface, narration comments, duplicated helper, docstring echo |
| **Optional** | Taste, or a suggestion the author may decline | Naming preference, alternative structure of equal merit |

Rules for the review itself:

- **Say why, and say what instead.** "This swallows the parse error, so a bad payload looks
  like an empty result — catch JSONDecodeError and re-raise with the URL" is actionable;
  "too defensive" is not.
- **Point at the line**, not the file.
- **Do not invent findings.** A review with four real issues beats one with four real and
  eleven padded — padding costs you the author's attention on the four that matter.
- **Verify before you claim.** If you say something is broken, say what input breaks it. If
  you cannot construct that input, say you are unsure instead of asserting.
- **Do not demand the abstraction you would have written.** Working, simple, locally
  consistent code is not a finding.
- **Say what is good, once and specifically**, if it is — it tells the author which
  instincts to keep.

## Receiving review feedback

- **Fix it or say why not.** Silence on a comment reads as ignoring it.
- **Disagreement is fine, with a reason.** "The caller above already validates this, so the
  check is unreachable — here is the line" is a reason. "It's safer" is not.
- **Fix the class, not the instance.** Three comments about narration comments means read
  the whole diff for narration, not delete three lines.
- **Never** weaken a test, skip a check, or delete a failing assertion to close a review
  comment. If a reviewer is wrong about a test, argue it; do not quietly disable it.
- **Re-run the checks after the fixes**, and report the new output. A "fixed" push that
  turns CI red costs a full cycle and the reviewer's trust.
