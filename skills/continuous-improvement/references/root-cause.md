# Root cause analysis (State 3)

The tools here **generate candidates**. They do not verify anything — that is what the
hypothesis tests in `hypothesis-testing.md` are for. Keeping that boundary visible is the
whole discipline: a fishbone diagram is a structured list of guesses, and treating its
most plausible branch as the answer is how teams implement expensive fixes for causes that
were never causes.

## Start with Pareto

Before generating causes, find out where the problem actually lives. Classify defects by
type, location, product, customer, or time, and sort by frequency.

```python
import numpy as np
counts = {"timeout": 412, "auth": 88, "validation": 61, "network": 25, "other": 14}
total = sum(counts.values())
cum = 0
for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
    cum += v
    print(f"{k:12s} {v:5d}  {v/total:6.1%}  cumulative {cum/total:6.1%}")
```

Usually a small number of categories carry most of the defects, and scoping the project to
them multiplies the return on every later hour. Weight by cost or customer impact rather
than raw count when they differ — 400 trivial defects may matter less than 25 that lose
accounts.

Pareto by *time* deserves a separate pass: a defect type that appeared in March is a
different investigation from one that has been constant for two years. The first has an
assignable cause and a date to anchor it to.

## Is / is-not analysis

Cheap, fast, and consistently underused. For the defect, state where it **is** observed and
where it is **not**:

| | Is | Is not |
|---|---|---|
| What | Timeouts on checkout | Timeouts on search |
| Where | EU region | US region |
| When | Since 14 March, peak hours | Off-peak, before March |
| Who | Mobile clients | Desktop clients |

The contrast does the work. Any proposed cause must explain both columns — why the defect
appears *here* and not *there*. A cause that would predict timeouts everywhere is refuted by
the "is not" column before you spend anything testing it. This single step eliminates more
bad hypotheses per minute than any other tool in the phase.

## Fishbone (Ishikawa)

Structured brainstorming against standard categories, so the team's blind spots become
visible.

**Manufacturing (6M):** Machine, Method, Material, Manpower, Measurement, Mother Nature.
**Service and software (often better):** People, Process, Technology, Information, Policy,
Environment.

Two things make the difference between a useful fishbone and wall decoration:

- **Include Measurement as a branch and take it seriously.** "The defect is a measurement
  artefact" is a genuine and common root cause, and it is cheap to check.
- **Mark each candidate with the evidence available**, so the diagram feeds State 3's test
  plan directly: which Xs are already in the baseline data, which need collecting, which
  can only be assessed by experiment.

## 5 Whys

Follow one causal chain down. Useful when the chain is genuinely linear and the team has
direct knowledge of the process.

Its well-known weakness: it produces a single path, so it finds *a* cause rather than *the*
cause, and the path taken depends on who is in the room. Use it to deepen a branch the
Pareto has already pointed at, not to select the branch.

Stop when you reach something you can actually change. "Because the developer made a
mistake" is not a root cause — it is a stopping point that blames a person and leaves the
system that permitted the mistake untouched. Keep going until you reach a process, a
control, or a design decision.

A worked chain:

```
Deploy failed
 -> the migration timed out
 -> it locked a table for 40 seconds
 -> it rewrites the whole table rather than adding a nullable column
 -> no review step checks migrations for locking behaviour   <- changeable
```

## FMEA: prioritizing what to fix

When several verified causes compete for attention, score each failure mode on Severity,
Occurrence and Detection (1–10 each); **RPN = S × O × D**.

Treat RPN as a conversation starter, not a ranking. It has a known flaw — multiplying
ordinal scales means an RPN of 200 is not twice as bad as 100 — so always fix high-Severity
items regardless of their product. A rare, undetectable, catastrophic failure can score
lower than a frequent nuisance.

FMEA earns its keep most in State 4, where the Detection column points directly at
poka-yoke opportunities: a failure that cannot be detected is one to design out rather
than monitor.

## Handing off to verification

Leave State 3 with a table, not a diagram:

| Candidate X | Source | Evidence available | Test | Result |
|---|---|---|---|---|
| Migration size | fishbone: Method | in deploy logs | 2-sample t-test | verified, p = 0.003, d = 1.2 |
| Time of day | is/is-not | in deploy logs | ANOVA | ruled out, p = 0.41 |
| Reviewer experience | 5 whys | needs collecting | — | not yet tested |

The "ruled out" rows are as valuable as the verified ones, and they are the rows most often
deleted before the readout. Keep them.
