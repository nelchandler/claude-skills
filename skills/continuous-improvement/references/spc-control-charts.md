# Statistical process control (States 2 and 5)

A control chart answers one question, and it is the question the whole method turns on:
**is this variation the process being itself, or is something different happening?**

## Common cause vs special cause

**Common cause** is the ordinary scatter inherent in the system — many small influences,
no assignable reason, a different number every day. **Special cause** is something
genuinely different: a new supplier, a changed config, an untrained operator.

They require opposite responses, and confusing them makes things actively worse:

- **Treating common cause as special is tampering.** Investigating each bad day, adjusting
  in response to noise, asking "what went wrong Tuesday?" when Tuesday sat inside the
  limits — all of it *increases* variation. Deming's funnel experiment is the canonical
  demonstration: a rule that adjusts after every deviation performs strictly worse than
  leaving the funnel alone. Improving a common-cause process means changing the system
  itself, and no amount of reacting to outputs will do it.
- **Treating special cause as common** means shrugging at a real signal and losing a
  findable, fixable reason.

Most management reporting — month-on-month deltas, red/amber/green on a single number,
"explain the variance" — is tampering with extra steps. Charting the same numbers usually
shows a stable process being asked to account for its own noise.

## Choosing the chart

Picking the wrong family is the most common SPC error. Attribute data on a variables chart
produces limits with no relation to the underlying binomial or Poisson spread.

```python
from spckit import chart_for
chart_for("continuous", subgroup_size=5)        # 'xbar_r'
chart_for("defective", varying_size=True)       # 'p_chart'
```

| Data | Condition | Chart |
|---|---|---|
| Continuous | one reading per period | **I-MR** |
| Continuous | subgroups of 2–10 | **X-bar / R** |
| Continuous | subgroups over ~10 | **X-bar / S** |
| Defective *units* (pass/fail) | varying sample size | **p** |
| Defective *units* | constant sample size | **np** |
| *Defects* per unit | constant opportunity | **c** |
| *Defects* per unit | varying opportunity | **u** |

The defective/defects distinction matters: a unit is defective or not (binomial, p/np),
while a unit may carry several defects (Poisson, c/u). Counting defects on a p-chart
understates the limits.

## Reading the charts

```python
from spckit import xbar_r, i_mr, nelson_rules
res = xbar_r(subgrouped_data)
print(res["r"])        # READ THIS FIRST
print(res["xbar"])
violations = nelson_rules(res["xbar"].points, res["xbar"].center, res["xbar"].sigma)
```

**Read the R (or S) chart before the X-bar chart, always.** The X-bar limits are computed
*from* R-bar, so if the spread is unstable those limits are meaningless — and chasing
phantom mean shifts on limits derived from unstable spread is a well-trodden way to waste
a month.

For I-MR, sigma comes from the average moving range (MR-bar / 1.128), never the standard
deviation of all the values. The overall standard deviation absorbs any drift into the
limits themselves, so a steadily drifting process ends up with limits wide enough to look
perfectly stable. This is the single most common way a chart is built to prove there is no
problem.

## The eight Nelson rules

Rule 1 catches the obvious. The rest catch a process drifting, cycling, or stratified while
every individual point sits inside the limits — which is precisely what a chart is worth
having for.

| # | Signal | Usually means |
|---|---|---|
| 1 | 1 point beyond 3σ | A special cause, now |
| 2 | 9 in a row on one side | The mean has shifted |
| 3 | 6 in a row rising or falling | Drift, wear, a trend |
| 4 | 14 in a row alternating | Over-adjustment (tampering), or two alternating sources |
| 5 | 2 of 3 beyond 2σ same side | A shift starting |
| 6 | 4 of 5 beyond 1σ same side | A smaller sustained shift |
| 7 | 15 in a row within 1σ | **Limits too wide** — usually stratified subgroups, not a great process |
| 8 | 8 in a row beyond 1σ both sides | **A mixture** of two populations |

Rules 7 and 8 are the ones people misread. Rule 7 looks like excellent performance and
almost always means the subgrouping is wrong — systematically different sources inside each
subgroup inflate R-bar and widen the limits. Rule 8 means you are charting two processes at
once; stratify and chart them separately.

Testing eight rules at once buys sensitivity at the cost of false alarms: on a stable
process roughly a third of 40-point series will signal *something* (spckit's tests measure
exactly this). So a signal means **investigate**, not adjust. If investigation finds no
assignable cause, that was a false alarm and the correct action is to do nothing.

Zone-based rules (2, 5–8) assume constant limits. On a p- or u-chart with varying sample
sizes the limits move, so apply rule 1 only — `spckit` flags this in the chart's notes.

## Setting and recomputing limits

Use **20–25 subgroups** to establish limits. Fewer makes the limits unstable estimates of
themselves.

If the baseline period contains a special cause with a *known, removed* assignable reason,
exclude those points and recompute. Never exclude a point merely for being inconvenient —
that is fitting the limits to the desired conclusion.

**Control limits are not specification limits, and the two have nothing to do with each
other.** Control limits come from the process (what it does); spec limits come from the
customer (what is acceptable). A process can be perfectly in control and produce entirely
out-of-spec parts. Never draw spec limits on a control chart — it invites the reader to
treat an in-spec-but-out-of-control point as fine, and every out-of-spec point as a special
cause.

In **State 5**, recompute the limits from post-improvement data. Carrying the old limits
forward means a genuinely improved process either alarms constantly (tighter spread, old
wide limits, rule 7 everywhere) or never alarms at all. Recomputing is the point of the
phase: the new limits are the standard the process will be held to.
