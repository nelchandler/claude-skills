# Hypothesis testing (State 3)

The phase that separates a verified root cause from a plausible story. Brainstorming
produces candidate Xs; only a test promotes one to a root cause, and the discipline of
insisting on that is most of what distinguishes Six Sigma from an opinionated meeting.

## Choosing the test

| Question | Y (output) | X (input) | Test |
|---|---|---|---|
| Do two groups differ in mean? | continuous | 2 groups | 2-sample t-test (Welch) |
| Do 3+ groups differ in mean? | continuous | 3+ groups | One-way ANOVA |
| Before vs after, same units? | continuous | paired | Paired t-test |
| Do groups differ in *spread*? | continuous | 2+ groups | Levene / Brown-Forsythe |
| Are two proportions different? | defective | 2 groups | 2-proportion z-test |
| Are defect rates related to a category? | counts | categories | Chi-square |
| Does a continuous X drive Y? | continuous | continuous | Regression, correlation |
| Non-normal, or small n? | continuous | 2+ groups | Mann-Whitney, Kruskal-Wallis, Mood's median |

```python
from scipy import stats

# Two groups -- Welch's t-test does not assume equal variances, so prefer it
t, p = stats.ttest_ind(group_a, group_b, equal_var=False)

# Three or more groups
f, p = stats.f_oneway(shift_a, shift_b, shift_c)

# Defect counts across categories
chi2, p, dof, expected = stats.chi2_contingency(table)

# Spread rather than centre -- often the real finding
w, p = stats.levene(group_a, group_b, center="median")
```

**Test the variances too, not just the means.** A change that leaves the mean untouched but
halves the spread is frequently the improvement the customer actually feels, and a
means-only analysis reports "no significant difference" and discards it.

## Assumptions, and what to do when they fail

- **Independence.** The one that matters most and is checked least. Consecutive
  measurements from one process are usually autocorrelated; repeated measures on the same
  unit are not independent observations. Violating it makes every p-value too small.
- **Normality.** Matters mainly for small samples; ANOVA and t-tests are fairly robust
  beyond n ≈ 30 per group. Check with a normal probability plot rather than a normality
  test — with large n, tests reject trivial, harmless departures. If it genuinely fails,
  use the non-parametric equivalent or transform.
- **Equal variances.** Use Welch's t-test (`equal_var=False`) by default; it costs almost
  nothing when variances are equal and saves you when they are not.

## Power: size the test before running it

An underpowered test that returns p > 0.05 has proved nothing — "no significant
difference" and "no difference" are different statements, and conflating them lets a real
root cause be dismissed.

```python
from statsmodels.stats.power import TTestIndPower
n = TTestIndPower().solve_power(effect_size=0.5, power=0.8, alpha=0.05)
```

Decide the effect size worth detecting from the CTQ, not from convention: if a 2-minute
cycle-time reduction would not change the business outcome, do not size the study to find
one.

## Statistical vs practical significance

With enough data everything is significant. A p-value says the effect is probably not
zero; it says nothing about whether the effect matters.

**Always report the effect size and a confidence interval on the difference**, and state
the practical meaning against the CTQ. "Shift B averages 0.3 seconds slower (95% CI 0.1 to
0.5, p = 0.004) on a 45-second cycle" is an honest finding that also makes plain it is not
the root cause worth chasing.

Useful effect sizes: **Cohen's d** for two means, **eta-squared** or **omega-squared** for
ANOVA (the share of variation explained — the number that tells you how much of the problem
this X accounts for), **Cramér's V** for chi-square.

## Multiple comparisons

Testing ten candidate Xs at α = 0.05 gives roughly a 40% chance of at least one false
positive. With a fishbone full of candidates this is not hypothetical — it is how a team
ends up implementing a fix for a cause that was noise.

Use ANOVA first to ask whether anything differs, then a post-hoc procedure that controls the
family-wise rate (Tukey HSD) to find which. For many independent tests, control the false
discovery rate (Benjamini-Hochberg). And say how many tests you ran — a p-value from an
undisclosed search is not evidence.

## Recording the result

For every candidate X, record: the test used, the p-value, the effect size, the share of
variation explained, and the verdict. **Keep the ruled-out candidates in the report.** A
tested-and-rejected cause is a real result: it stops the team relitigating it in three
months, and it is the part of the analysis that survives longest.
