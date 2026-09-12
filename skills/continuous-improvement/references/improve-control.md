# Improve and Control (States 4 and 5)

## Generating solutions

Every solution must trace to a **verified** root cause from State 3. A solution with no such
parent is a preference, and implementing it spends the project's credibility on a guess.

Prefer, in this order — the ranking is by durability, not by effort:

1. **Eliminate the cause** — remove the step, the handoff, the decision entirely.
2. **Mistake-proof it (poka-yoke)** — make the error impossible rather than unlikely. A
   required field, a type that cannot hold an invalid value, a connector that only fits one
   way, a CI check that blocks the merge.
3. **Automate the control** — remove the reliance on someone remembering.
4. **Simplify** — fewer steps, fewer handoffs, less to get wrong.
5. **Train and document** — the weakest, because it decays. Necessary, rarely sufficient.

Solutions that depend on sustained human vigilance regress to baseline within months. That
is not a comment on the people; it is what "vigilance" means as a control mechanism.

## Selecting between solutions

**Impact / effort grid** — quick triage into do-now (high impact, low effort), plan,
question, and drop.

**Pugh matrix** — for comparing several options against the current state on multiple
criteria. Score each option against the baseline as better (+), same (S), or worse (−), then
count. Its value is less the arithmetic than the argument it forces: disagreement about a
cell surfaces a disagreement about criteria, which is the conversation worth having.

Weight the criteria *before* scoring. Weighting afterwards lets the preferred answer pick
its own weights, which is exactly the failure mode the matrix exists to prevent.

## Design of experiments

When several Xs may interact, one-factor-at-a-time testing is both slower and blind to the
interaction — and interactions are frequently where the answer is.

A **2^k factorial** tests k factors at two levels each: 3 factors = 8 runs, and you get all
main effects *and* all interactions. For more factors, a **fractional factorial** (2^(k-p))
trades resolvable interactions for run count; Resolution IV or V keeps main effects clean.

Practical discipline: **randomize the run order** (it protects against drift in an
uncontrolled variable), **replicate** (without replication there is no error estimate and
so no significance test), **centre points** (they detect curvature you would otherwise miss
entirely), and **block** known nuisance factors like day or batch rather than hoping they
average out.

## Piloting

State the success criteria **before the pilot runs**. Choosing them afterwards is how noise
gets promoted to a win, and it is the single most common way improvement projects report
gains that do not persist.

The pilot design needs: duration and sample size (sized for the effect you need to detect —
see power in `hypothesis-testing.md`), pre-stated success criteria tied to the CTQ, the
comparison method, a rollback plan, and the stratification factors to keep recording.

Run it long enough to cross the process's natural cycles. A pilot spanning one week of a
process with strong weekly seasonality measures the week, not the change.

## Verifying the improvement (State 5)

```python
from scipy import stats
from spckit import capability, i_mr, nelson_rules

t, p = stats.ttest_ind(before, after, equal_var=False)
diff = after.mean() - before.mean()
# Report the interval on the difference, not just p
```

Report all four: the **size** of the change, its **confidence interval**, its **statistical
significance**, and its **practical significance** against the CTQ. A statistically
significant 0.4% improvement on a metric that needed 20% is a null result written
optimistically.

Check the **spread** as well as the mean — `stats.levene` — since a stabler process with the
same average is often the real gain, and a means-only comparison throws it away.

And chart the post-change data rather than comparing two averages. A step change shows up
as a clean shift in the chart; a "before and after" comparison cannot distinguish that from
a process that was drifting all along.

## Holding the gains

**Recompute the control limits** from post-improvement data. Carrying the old limits forward
means an improved process either alarms constantly or never alarms at all. The new limits
are the standard the process will now be held to — that is what State 5 is for.

The **control plan** is the deliverable that decides whether this project still matters in a
year:

| CTQ | Chart | Limits | Frequency | Owner | Reaction if out of control |
|---|---|---|---|---|---|

Every row needs a **named owner** and a **specific reaction plan**. "Investigate" is not a
reaction plan; "page the on-call, roll back the last migration, open an incident" is.

Then: update the SOP so the new method is the documented one, train the people who run it,
remove the old path where you can (a poka-yoke beats a procedure), and schedule a review —
30 and 90 days — to confirm the gain held.

An improvement with no owner and no monitoring decays to baseline, and the next team runs
the same project again from Define.
