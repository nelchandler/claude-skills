# Experimental design and analysis (States 7–8)

This is where a working model becomes a defensible number. The helpers referenced here
live in `scripts/simkit.py`; import them rather than rewriting the arithmetic.

## Terminating vs steady-state — decide first

The whole design follows from this, so settle it before anything else.

**Terminating**: the run has a natural end (a shift, a day, a project, a product life).
The initial condition is part of the system, so there is *no* warm-up to remove. Each
replication is one independent observation; run n of them and apply a t interval.

**Steady-state**: you want the long-run behavior and the initial state is an artefact.
Two valid designs:

- *Replication-deletion*: n independent replications, discard the warm-up from each,
  average within each run, then treat the n run-averages as independent observations.
  Simpler to reason about and parallelizes perfectly. Prefer it.
- *Batch means*: one very long run, discard the warm-up once, split the remainder into
  large batches, treat batch means as observations. Wastes less time on warm-up when the
  transient is long relative to the run.

Mixing them up is the usual error: reporting steady-state queue statistics from a short
terminating-style run that started empty and idle biases every queue metric downward,
often by more than the effect being measured.

## Warm-up (steady-state only)

Welch's graphical procedure: average the output process across replications at each time
index to suppress noise, smooth with a moving average, and truncate where the curve
flattens.

```python
from simkit import welch_warmup
truncation, smoothed = welch_warmup(replication_traces, window=25)   # (n_reps, time)
```

Use 10 or more replications — more replications beats a wider smoothing window, because
the window trades away the resolution you need to see where the curve settles. Then plot
`smoothed` and confirm the suggested index by eye; the function returns a heuristic
reading, and Welch's method is graphical by intent.

Be generous with truncation. Discarding twice as much as you need costs a little compute;
discarding too little biases every result. Where the transient is long, extend the run
rather than shrinking the truncation.

## How many replications

Derive n from the precision the decision needs. Guessing 1000 is not a design.

```python
from simkit import n_for_halfwidth, mc_summary
pilot = [run_one(params, seed).kpis()["mean_wait_min"] for seed in range(20)]
n = n_for_halfwidth(pilot, target_half_width=0.5)        # +/- 0.5 minutes at 95%
n = n_for_halfwidth(pilot, 0.05, relative=True)          # +/- 5%
```

The arithmetic is `n >= (z * s / h)²`, so precision costs quadratically: halving the
interval takes four times the runs. That is exactly why the target should come from the
decision — if two options differ by 3 minutes, resolving to ±0.5 is waste and ±1 is
plenty. After the full run, re-check the achieved half-width, since the pilot's variance
estimate is itself noisy and n may need a top-up.

For a steady-state batch-means design, the equivalent lever is run length, and the check
is the batch autocorrelation:

```python
from simkit import batch_means
result = batch_means(series_after_warmup, n_batches=20)
print(result)            # prints warnings if the batches are still correlated
```

Never apply a t interval to a raw autocorrelated time series. It is the most common way
simulation studies overstate precision, and the error is large — a factor of several, not
a few percent.

## Variance reduction: do this before buying CPU

### Common random numbers (CRN) — the one that always pays

When comparing scenarios, run them on the *same* seeds and compare replication i to
replication i. Shared randomness cancels in the difference, so the interval on the
difference can be an order of magnitude tighter than either scenario's own interval.

```python
from simkit import seed_streams, crn_compare
seeds = list(range(200))
base = [run_one(baseline_params, s).kpis()[kpi] for s in seeds]
alt  = [run_one(alt_params, s).kpis()[kpi] for s in seeds]
print(crn_compare(base, alt))   # paired difference, CI, achieved variance reduction
```

CRN only works if the streams stay aligned, which is why each source of randomness needs
its own stream (see the reproducibility section of SKILL.md). If the scenario changes the
*number* of draws from a shared generator — an extra server consuming service times in a
different order — alignment breaks and the pairing silently stops helping.
`crn_compare` reports the achieved variance reduction for exactly this reason: a value
near 1 means the runs were not actually paired, and that is a bug to fix, not a result.

CRN tightens *differences*, not absolute levels. Absolute KPIs still need their own n.

### Others, in rough order of usefulness

- **Latin hypercube / Sobol sampling** for input sweeps: far better coverage of a
  multi-dimensional parameter space than an equal number of random points, and the
  natural choice for sensitivity analysis.
- **Control variates** when some correlated quantity has a known expectation (a
  deterministic bound, a simplified analytic version of the model). Cheap and effective
  where one is available.
- **Antithetic variates**: pair each run with one using `1 - u`. Helps when the output is
  close to monotone in the inputs; can backfire otherwise, so measure the achieved
  variance rather than assuming a gain.
- **Importance sampling / splitting** for rare events. Not an optimization — below
  p ≈ 1e-4 brute force is simply infeasible (`rare_event_n(1e-4)` returns tens of
  millions), so this is the only route to an answer.

## Comparing scenarios (State 8)

**Two scenarios.** Paired t-test on the CRN differences via `crn_compare`. Report the
confidence interval on the difference; the interval is what answers the decision, and
"not significant" with a ±0.2-minute interval means something quite different from "not
significant" with a ±8-minute one.

**Three or more.** ANOVA to test whether any scenario differs, then a post-hoc procedure
that controls the family-wise error rate — otherwise testing many scenarios manufactures
a winner by chance alone.

```python
from scipy import stats
import statsmodels.stats.multicomp as mc

f_stat, p = stats.f_oneway(*scenario_results)         # any difference at all?
tukey = mc.pairwise_tukeyhsd(values, labels)          # which pairs, family-wise corrected
```

With CRN the observations are paired across scenarios, which violates one-way ANOVA's
independence assumption. Use a repeated-measures design (two-way ANOVA blocking on the
seed, or `statsmodels` mixed model) — blocking on the seed is what converts CRN's
pairing into extra power rather than a violated assumption.

**Selecting the best of many.** For a formal guarantee that the selected scenario is
within a tolerance of the true best, use ranking-and-selection (a two-stage Rinott
procedure) rather than reading off the largest sample mean, which is biased upward by
selection.

## Sensitivity analysis

Report which inputs drive the answer — it tells the reader where to spend data-collection
effort and which assumptions endanger the recommendation.

- **One-at-a-time** sweeps: cheap, interpretable, blind to interactions.
- **Factorial or fractional factorial** designs: capture main effects and interactions
  with a manageable number of runs. A 2^k design over k factors at high/low levels is the
  standard starting point.
- **Sobol indices** for a global variance decomposition when the budget allows.

Present the result as a ranked table — factor, effect on the KPI, whether it flips the
recommendation. A tornado chart communicates it in one glance.

## Reporting

Every number carries an interval. Say the n and where it came from. Say the warm-up and
how it was chosen. Say the master seed. State whether the comparison used CRN. And when
the intervals overlap, report that the data cannot distinguish the options — that is a
finding the decision-maker needs, not a failure of the study.
