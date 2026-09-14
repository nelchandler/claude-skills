# claude-skills

[Claude Code](https://claude.com/claude-code) skills, packaged as an installable plugin
marketplace so they work in every project rather than one repo.

## Install

```bash
/plugin marketplace add nelchandler/claude-skills
/plugin install skills@nelchandler
```

Or non-interactively:

```bash
claude plugin marketplace add nelchandler/claude-skills
claude plugin install skills@nelchandler
```

Update later with `/plugin marketplace update nelchandler`.

## Skills

### simulation-engineer

An Operations Research and simulation engineering agent. It runs the standard 8-step
simulation lifecycle as an explicit state machine — problem formulation, conceptual
modeling, input modeling, translation, verification, validation, experimental design,
execution and analysis — and does not skip steps.

The reason for the gating: simulation output is plausible by construction. A model with an
invented arrival distribution and no warm-up analysis still prints a tidy mean queue length
to three decimals, and a stakeholder cannot tell that number from a real one. Each step has
a gate that must clear before the next begins.

Covers discrete-event (`simpy`), agent-based (`mesa`), system dynamics, static Monte Carlo,
and Markov/regime-switching models, with reference material per paradigm:

| Reference | Contents |
|---|---|
| `input-modeling.md` | Distribution fitting, K-S and chi-square caveats, three-point/PERT estimates, copulas for correlated inputs |
| `discrete-event.md` | simpy structure, queue disciplines, M/M/1 and Little's Law verification, common DES mistakes |
| `agent-based.md` | mesa scheduling regimes, mean-field checks, pattern-oriented validation |
| `markov-economic.md` | Closed forms before simulation, regime switching, exact vs Euler SDE schemes |
| `experiment-design.md` | Welch warm-up, replication sizing, common random numbers, batch means, ANOVA, rare events |

**Trigger it** by describing anything stochastic you want sized or compared — queues,
capacity, staffing, throughput, lead times, inventory, risk, load models, regime-switching
paths, what-if scenarios — or type `START` for the guided workflow from step 1.

#### Bundled tooling

`skills/simulation-engineer/scripts/simkit.py` is the statistics every simulation study
otherwise re-derives, with the parts that are easy to get subtly wrong done once:

- `seed_streams` — independent RNG streams via `SeedSequence.spawn`, not `seed + i`
- `mc_summary` / `bootstrap_ci` — Student-t and percentile-bootstrap intervals
- `n_for_halfwidth` — replications needed for a target precision, instead of guessing 1000
- `batch_means` — steady-state intervals from one long run, warning when batches stay correlated
- `welch_warmup` — warm-up truncation point from replication traces
- `crn_compare` — paired scenario comparison that reports its *achieved* variance reduction,
  so broken common-random-number alignment shows up as a number rather than a silent loss

Requires `numpy`. `scipy` is optional — quantiles fall back to Acklam and Cornish-Fisher
approximations when it is absent, so the module works in a bare environment. `simpy` and
`mesa` are only needed for those paradigms.

```bash
pip install numpy scipy          # scipy optional but recommended
pip install simpy mesa           # per paradigm, as needed
```

#### Tests

29 tests covering the statistics rather than merely execution — quantiles against published
values, interval coverage against its nominal rate, batch means against an AR(1) process with
known autocorrelation, stream independence under changed draw order, and common random
numbers where the variance reduction is analytically predictable.

```bash
cd skills/simulation-engineer/scripts
python -m pytest test_simkit.py -q
```

### continuous-improvement

A Lean Six Sigma agent that runs DMAIC — Define, Measure, Analyze, Improve, Control — as a
gated state machine: process capability, measurement system analysis, SPC control charts
with Nelson rules, hypothesis testing to prove root causes rather than guess them, and
control plans that hold the gains. Bundles `spckit.py` for the limits, capability indices
and Gage R&R that are tedious to look up and easy to transcribe wrongly.

**Trigger it** with any process you want to improve or stabilise — defect rates, cycle
time, lead time, throughput, rework, yield, deployment failure rate, incident volume — or
ask why a process got worse, or whether a change actually helped.

### no-slop-coding

Writes and reviews code a senior engineer would sign off on, and strips what makes
generated diffs recognisable: speculative abstractions, one-caller wrappers, `except
Exception: pass`, comments restating the code, duplicated helpers, compat shims nobody
asked for, tests that cannot fail, `SUMMARY.md` files.

The reason it is a skill rather than a style guide: the default pull when generating code
is toward *adding* — another guard, another wrapper, another file — and each addition looks
like diligence in isolation. Together they are why a 20-line change arrives as a 400-line
diff. So the working question for every line is not "could this help?" but "what breaks if
I delete it?"

It also says where verbosity is *correct* — error messages, public API contracts, test
names, validation at a trust boundary — because over-correcting into terseness is its own
failure.

| Reference | Contents |
|---|---|
| `slop-catalog.md` | The patterns one by one, with before/after: parallel implementations, speculative generality, defensive swallowing, narration, docstring echoes, compat shims, `utils.py`, tests that cannot fail |
| `comments-docs-naming.md` | Which comments earn their place, when a docstring is worth writing, naming rules that survive contact with real code |
| `errors-and-tests.md` | Catch what you can handle where you can handle it; how to tell a real test from a green one |
| `review-pass.md` | Reading a diff (yours or someone else's), severity levels for review comments, receiving feedback |

**Trigger it** before writing, refactoring or reviewing anything, and again before
committing — or by saying slop, bloat, over-engineered, clean this up, make it idiomatic,
or asking for a review of a diff.

#### Bundled tooling

`skills/no-slop-coding/scripts/slopcheck.py` finds the mechanical cases so the review pass
can spend its attention on judgement:

```bash
python3 slopcheck.py --diff              # added lines vs HEAD, plus diff shape
python3 slopcheck.py src/ tests/         # a whole tree
```

Findings (exit 1): swallowed exceptions, definitions referenced nowhere else, compat shims,
duplicated blocks, commented-out code, debugger statements, scaffolding filenames.
Advisories (exit 0): comments restating their line, unowned `TODO`s. Standard library only,
no dependencies.

The precision work is where the value is — a detector that fires on good code gets ignored,
and the one real finding goes with the noise. So `breakpoint()` inside a string literal is
not a debugger statement, prose that mentions a `TODO` is not one, a document *describing*
a pattern is not an instance of it, and English rarely parses as Python, which is what
separates a commented-out call from a comment. A clean run is still not a clean diff:
nothing here detects a one-caller wrapper or a test that cannot fail.

#### Tests

65 tests, mostly *negative* — the correct version of each pattern has to stay silent — with
every check pinned by both a hit and a near-miss. The suite is mutation-tested: nine
deliberate breakages of the detector (inverting the broad-except test, dropping the
new-file flag, unanchoring the `TODO` pattern, shrinking the duplicate window, removing the
diff filter) are each caught by a failing test.

```bash
cd skills/no-slop-coding/scripts
python -m pytest test_slopcheck.py -q
```

## Adding another skill

The whole repository is one plugin, so a new skill is one directory and no manifest edits:

```bash
python3 scripts/new_skill.py <skill-name> [--with-references] [--with-scripts]
```

which stamps out the directory and a frontmatter template:

```
skills/<skill-name>/SKILL.md          # required
skills/<skill-name>/references/       # optional, loaded on demand
skills/<skill-name>/scripts/          # optional
```

The **directory name** is what makes `/<skill-name>` work; the `name:` field in
frontmatter is display-only. The `description:` is what Claude reads to decide whether to
invoke the skill, so it carries the whole triggering burden:

```yaml
---
name: skill-name
description: >-
  <what it does, 1-2 sentences>
  Use this skill whenever <concrete situations>.
  Use it too when <indirect signals: symptoms, filenames, library names> even if
  the user never says the obvious keyword.
---
```

Keep `description` under 1,536 characters (the cap, shared with `when_to_use` if used).
Under-triggering is the usual failure, so enumerate situations rather than writing a bare
category label, and put when-to-use in the description — never only in the body, which
isn't loaded until after the decision to fire has been made.

### Cross-references

Skills that hand off to each other should say so, in a `## Related skills` section at the
end of `SKILL.md`. A skill's body is only loaded once that skill fires, so this is how a
project already underway in one skill discovers that another one covers the next step —
nothing else surfaces it.

The scaffold lists every existing skill in that section so the pointer gets written while
you still remember the relationship; delete the lines that aren't genuinely related.

Say **when** the handoff happens, not just that the other skill exists:

```markdown
## Related skills

- `simulation-engineer` — at **State 4**, when the proposed change is to capacity,
  staffing or queue discipline. Those effects are non-linear and hard to reason about,
  so modelling the change beats guessing at it before a pilot.
```

`--check` treats a pointer to a skill that doesn't exist as an **error** — a dangling
reference sends the reader after nothing, and a rename would otherwise break it silently.
It prints the cross-reference graph so you can see what points where.

### Validate

Before committing:

```bash
python3 scripts/new_skill.py --check
```

`--check` exits non-zero on errors, so it works as a pre-commit hook or CI step. It
catches the mistakes that otherwise fail *silently* — a description over the cap gets
truncated with no error, a misspelled frontmatter key is ignored, a skill directory with
no `SKILL.md` is simply invisible, and a `name:` that disagrees with its directory misleads
every later reader. It also warns on the softer stuff: descriptions that never say when to
use the skill, bare category labels, and template placeholders left unedited.

Existing installs pick up new skills on `/plugin marketplace update nelchandler`.

## License

MIT — see [LICENSE](LICENSE).
