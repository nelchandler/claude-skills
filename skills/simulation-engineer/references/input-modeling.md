# Input modeling (State 3)

Every stochastic input needs a defended distribution. This is the step most often
skipped, and it is the one that most directly determines whether the output means
anything: a queueing model fed a normal service time when the truth is lognormal will
understate the tail badly, and no amount of extra replications repairs it.

## With data

### 1. Look before fitting

Plot a histogram and an empirical CDF. Check the support (bounded? non-negative?),
the skew, whether the tail is heavy, and whether the data are multimodal. A bimodal
service time usually means two entity classes were pooled — split them and fit each,
rather than fitting a compromise distribution that describes neither.

Check independence too. Autocorrelated inter-arrival times, or service times that
depend on time of day, break the i.i.d. assumption that every fit below relies on.
A time-varying arrival rate is a non-stationary Poisson process, not a badly fitting
exponential; model it with a piecewise-constant rate by period.

### 2. Fit candidates

Pick candidates by mechanism, not by scanning every distribution in `scipy.stats`.

| Quantity | Start with | Why |
|---|---|---|
| Inter-arrival times, independent arrivals | Exponential | Memoryless Poisson arrivals |
| Counts per interval | Poisson, negative binomial | NB when variance exceeds the mean |
| Service / repair / task duration | Lognormal, gamma, Weibull | Non-negative, right-skewed |
| Time to failure | Weibull, exponential | Shape parameter encodes wear-in vs wear-out |
| Sum of many small effects | Normal | CLT; check that negatives are impossible |
| Proportion, yield | Beta | Bounded on [0, 1] |
| Bounded expert estimate | Triangular, PERT/beta | See below |

```python
from scipy import stats
candidates = {"lognorm": stats.lognorm, "gamma": stats.gamma, "weibull_min": stats.weibull_min}
fits = {}
for name, dist in candidates.items():
    params = dist.fit(data, floc=0)          # floc=0 for non-negative quantities
    ks = stats.kstest(data, name, args=params)
    k = len(params)
    ll = dist.logpdf(data, *params).sum()
    fits[name] = {
        "params": params,
        "ks_stat": ks.statistic,
        "ks_p": ks.pvalue,
        "aic": 2 * k - 2 * ll,
    }
```

### 3. Test the fit

- **K-S test** for continuous data. Note the caveat: the standard p-value assumes the
  parameters were *not* estimated from the same data. Fitting first makes the test
  optimistic, so treat a marginal pass as a fail and prefer the ranking by K-S
  statistic over the absolute p-value.
- **Chi-square test** for discrete data or binned continuous data. Keep expected cell
  counts at 5 or more, pooling tail bins if needed; the test is unreliable otherwise.
- **Anderson-Darling** when the tail is what the decision depends on — it weights the
  tails more heavily than K-S does.
- **Q-Q plot** always. It shows *where* a fit fails, which the single test statistic
  hides, and tail misfit is exactly what matters for capacity questions.

Report a ranked table: distribution, parameters, K-S statistic, p-value, AIC. State
which you chose and why. When nothing fits, that is the finding — say so and use the
empirical distribution below rather than forcing a parametric form.

### 4. When nothing fits

Sample from the empirical distribution directly (bootstrap the observed values), or
fit a piecewise-linear empirical CDF for interpolation between them. The cost is that
you can never generate a value more extreme than what history contains — which
matters for tail-driven decisions, so say it out loud in the assumptions list.

### Sample size

Below ~50 observations, distribution choice is barely identifiable; below ~20, treat
the fit as an expert estimate with data-flavored parameters and carry the uncertainty
into State 8 as a sensitivity case rather than pretending to a fitted answer.

## Without data: three-point estimates

Elicit optimistic (a), most likely (m), pessimistic (b) from someone who knows the
process, and be explicit that a and b mean near-extremes, not absolute bounds — people
routinely give a 90% interval when asked for a range.

**Triangular**: `rng.triangular(a, m, b)`. Simple, bounded, no tail beyond b. Good
default when the expert is confident about the bounds.

**PERT (scaled beta)**: smoother and less weighted to the extremes than triangular,
which is usually more realistic for task durations.

```python
def pert(a, m, b, rng, lam=4.0):
    """PERT/beta-PERT sample. mean = (a + lam*m + b) / (lam + 2)."""
    mean = (a + lam * m + b) / (lam + 2.0)
    if m == mean:
        alpha = beta_ = (lam + 2.0) / 2.0
    else:
        alpha = ((mean - a) * (2.0 * m - a - b)) / ((m - mean) * (b - a))
        beta_ = alpha * (b - mean) / (mean - a)
    return a + rng.beta(alpha, beta_) * (b - a)
```

Label every such input "expert estimate, unvalidated" in the State 8 assumptions
section, and put the ones the recommendation is sensitive to into a sweep.

## Correlated inputs

Sampling correlated inputs independently understates aggregate variance, and almost
always in the reassuring direction — a portfolio of independent demands looks far safer
than one where demands move together. If inputs co-vary, induce the correlation:

- **Normal copula**: draw from a multivariate normal with the target correlation, map
  each margin through `norm.cdf`, then through the target marginal's `ppf`. Preserves
  each marginal exactly while imposing rank correlation.
- **Direct multivariate normal** when all margins really are normal.
- Note that Pearson correlation is not preserved exactly through the copula transform;
  match Spearman rank correlation instead, which is.

## Random variate generation notes

- Use `numpy.random.Generator` methods (`rng.exponential`, `rng.lognormal`) rather than
  hand-rolled inverse transforms; they are faster and better tested.
- Draw in blocks (`size=n`) rather than one value per call inside a loop when the model
  allows it — per-call overhead dominates otherwise.
- For a non-stationary Poisson process, use thinning: generate at the maximum rate and
  accept each arrival with probability `rate(t) / rate_max`.
