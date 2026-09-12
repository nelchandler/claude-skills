"""simkit -- the statistics every simulation study repeats.

Seeding, confidence intervals, replication sizing, warm-up detection, batch means,
and paired scenario comparison. Import these rather than re-deriving them per study:
the arithmetic is easy to get subtly wrong (a z where a t belongs, a variance
computed across correlated observations) and wrong intervals are invisible in output.

Depends on NumPy. Uses scipy.stats for exact t quantiles when it is installed and
falls back to a Cornish-Fisher expansion accurate to ~1e-5 for df >= 5 when it is not,
so the module works in a bare environment.

    from simkit import seed_streams, mc_summary, n_for_halfwidth, crn_compare
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

import numpy as np

try:  # exact quantiles when available; the fallback below is close but not exact
    from scipy import stats as _scipy_stats
except ImportError:  # pragma: no cover - exercised by the no-scipy path in tests
    _scipy_stats = None

__all__ = [
    "seed_streams",
    "MCSummary",
    "mc_summary",
    "n_for_halfwidth",
    "rare_event_n",
    "bootstrap_ci",
    "convergence_trace",
    "batch_means",
    "BatchMeansResult",
    "welch_warmup",
    "crn_compare",
    "CRNResult",
    "normal_quantile",
    "t_quantile",
]


# --------------------------------------------------------------------------- #
# Quantiles
# --------------------------------------------------------------------------- #

_ACKLAM_A = (
    -3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
    1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00,
)
_ACKLAM_B = (
    -5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
    6.680131188771972e01, -1.328068155288572e01,
)
_ACKLAM_C = (
    -7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
    -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00,
)
_ACKLAM_D = (
    7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
    3.754408661907416e00,
)


def normal_quantile(p: float) -> float:
    """Inverse standard normal CDF (Acklam's rational approximation, ~1e-9)."""
    if not 0.0 < p < 1.0:
        raise ValueError(f"p must be in (0, 1), got {p}")
    if _scipy_stats is not None:
        return float(_scipy_stats.norm.ppf(p))
    a, b, c, d = _ACKLAM_A, _ACKLAM_B, _ACKLAM_C, _ACKLAM_D
    p_low = 0.02425
    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    if p <= 1.0 - p_low:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (
            ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0
        )
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
        (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
    )


def t_quantile(p: float, df: int) -> float:
    """Inverse Student-t CDF.

    Small samples are the norm in simulation studies -- 10 replications is a
    perfectly ordinary pilot run -- and using a z quantile there understates the
    interval by around 15%, which is exactly the regime where an honest interval
    matters most.
    """
    if df < 1:
        raise ValueError(f"df must be >= 1, got {df}")
    if _scipy_stats is not None:
        return float(_scipy_stats.t.ppf(p, df))
    z = normal_quantile(p)
    v = float(df)
    z2, z3 = z * z, z ** 3
    z5, z7, z9 = z ** 5, z ** 7, z ** 9
    return (
        z
        + (z3 + z) / (4.0 * v)
        + (5.0 * z5 + 16.0 * z3 + 3.0 * z) / (96.0 * v ** 2)
        + (3.0 * z7 + 19.0 * z5 + 17.0 * z3 - 15.0 * z) / (384.0 * v ** 3)
        + (79.0 * z9 + 776.0 * z7 + 1482.0 * z5 - 1920.0 * z3 - 945.0 * z)
        / (92160.0 * v ** 4)
    )


# --------------------------------------------------------------------------- #
# Seeding
# --------------------------------------------------------------------------- #

def seed_streams(
    master_seed: int,
    n: int | None = None,
    labels: Sequence[str] | None = None,
) -> list[np.random.Generator] | dict[str, np.random.Generator]:
    """Derive independent RNG streams from one master seed.

    Give every replication -- and every distinct source of randomness inside a
    replication -- its own stream. Sharing one generator couples them: inserting a
    single extra draw for arrivals shifts the service times too, so two model
    versions become impossible to compare and common random numbers stop working.

        rngs = seed_streams(20260912, n=200)             # one per replication
        s = seed_streams(20260912, labels=["arrivals", "service", "routing"])
        s["arrivals"].exponential(1 / lam)

    Streams from SeedSequence.spawn are statistically independent, unlike streams
    seeded with master_seed + i, which can correlate.
    """
    if (n is None) == (labels is None):
        raise ValueError("pass exactly one of n= or labels=")
    seq = np.random.SeedSequence(master_seed)
    if labels is not None:
        children = seq.spawn(len(labels))
        return {name: np.random.default_rng(c) for name, c in zip(labels, children)}
    return [np.random.default_rng(c) for c in seq.spawn(int(n))]


# --------------------------------------------------------------------------- #
# Intervals and replication sizing
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class MCSummary:
    """A point estimate that carries its own uncertainty."""

    n: int
    mean: float
    std: float
    stderr: float
    half_width: float
    confidence: float

    @property
    def ci(self) -> tuple[float, float]:
        return (self.mean - self.half_width, self.mean + self.half_width)

    @property
    def relative_half_width(self) -> float:
        return float("inf") if self.mean == 0 else abs(self.half_width / self.mean)

    def __str__(self) -> str:
        lo, hi = self.ci
        return (
            f"{self.mean:.6g} +/- {self.half_width:.4g} "
            f"[{lo:.6g}, {hi:.6g}] {self.confidence:.0%} CI, n={self.n}"
        )


def mc_summary(samples: Iterable[float], confidence: float = 0.95) -> MCSummary:
    """Mean with a Student-t confidence interval.

    The samples must be independent -- one per replication, or batch means from a
    single long run. Feeding in a raw autocorrelated time series produces an
    interval several times too narrow, which is the single most common way
    simulation studies overstate their own precision.
    """
    x = np.asarray(list(samples), dtype=float).ravel()
    n = x.size
    if n < 2:
        raise ValueError("need at least 2 independent observations for an interval")
    mean = float(x.mean())
    std = float(x.std(ddof=1))
    stderr = std / math.sqrt(n)
    crit = t_quantile(1.0 - (1.0 - confidence) / 2.0, n - 1)
    return MCSummary(n, mean, std, stderr, crit * stderr, confidence)


def n_for_halfwidth(
    pilot: Iterable[float],
    target_half_width: float,
    confidence: float = 0.95,
    relative: bool = False,
) -> int:
    """Replications needed to reach a target CI half-width, from a pilot run.

    This is how State 7 picks n. Precision costs quadratically -- halving the
    interval takes four times the runs -- so deciding the precision the decision
    actually needs, before spending CPU, is the whole game. Returns the n implied
    by the pilot's variance; re-check after the full run, since the pilot's
    variance estimate is itself noisy.

        n = n_for_halfwidth(pilot_results, 0.5)        # +/- 0.5 minutes
        n = n_for_halfwidth(pilot_results, 0.05, relative=True)   # +/- 5%
    """
    pilot_summary = mc_summary(pilot, confidence)
    if target_half_width <= 0:
        raise ValueError("target_half_width must be positive")
    target = (
        target_half_width * abs(pilot_summary.mean) if relative else target_half_width
    )
    if target == 0:
        raise ValueError("relative target is undefined when the pilot mean is 0")
    z = normal_quantile(1.0 - (1.0 - confidence) / 2.0)
    n = math.ceil((z * pilot_summary.std / target) ** 2)
    return max(int(n), 2)


def rare_event_n(p: float, relative_error: float = 0.1, confidence: float = 0.95) -> int:
    """Runs a crude estimator needs to pin down a probability p.

    Call this before committing to brute force. The count scales as 1/p, so a
    1-in-10,000 event needs on the order of 1e7-1e8 runs for a usable interval --
    at which point importance sampling or splitting is not an optimization but the
    only viable approach.
    """
    if not 0.0 < p < 1.0:
        raise ValueError(f"p must be in (0, 1), got {p}")
    z = normal_quantile(1.0 - (1.0 - confidence) / 2.0)
    return max(int(math.ceil(z ** 2 * (1.0 - p) / (p * relative_error ** 2))), 2)


def bootstrap_ci(
    samples: Iterable[float],
    statistic: Callable[[np.ndarray], float] = np.mean,
    confidence: float = 0.95,
    resamples: int = 10_000,
    rng: np.random.Generator | None = None,
) -> tuple[float, tuple[float, float]]:
    """Percentile bootstrap interval for any statistic.

    Use it when the estimator is not a mean -- a 95th percentile, a ratio, a
    maximum queue length. The t interval in mc_summary does not apply to those,
    and capacity decisions usually hinge on exactly such tail statistics.
    """
    x = np.asarray(list(samples), dtype=float).ravel()
    if x.size < 2:
        raise ValueError("need at least 2 observations to bootstrap")
    rng = rng or np.random.default_rng(0)
    idx = rng.integers(0, x.size, size=(resamples, x.size))
    boot = np.apply_along_axis(statistic, 1, x[idx])
    alpha = (1.0 - confidence) / 2.0
    lo, hi = np.quantile(boot, [alpha, 1.0 - alpha])
    return float(statistic(x)), (float(lo), float(hi))


def convergence_trace(
    samples: Iterable[float], points: int = 25, confidence: float = 0.95
) -> list[tuple[int, float, float]]:
    """Running (n, mean, half_width) so you can see whether the estimate settled.

    A trace that is still drifting at the final n means n is too small, regardless
    of how tidy the last interval looks. Plot it, or scan the last few rows.
    """
    x = np.asarray(list(samples), dtype=float).ravel()
    if x.size < 2:
        raise ValueError("need at least 2 observations for a trace")
    ns = np.unique(np.linspace(2, x.size, num=min(points, x.size - 1), dtype=int))
    out = []
    for n in ns:
        s = mc_summary(x[:n], confidence)
        out.append((int(n), s.mean, s.half_width))
    return out


# --------------------------------------------------------------------------- #
# Steady-state analysis
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class BatchMeansResult:
    summary: MCSummary
    n_batches: int
    batch_size: int
    lag1_autocorr: float
    warnings: tuple[str, ...] = field(default=())

    def __str__(self) -> str:
        head = f"{self.summary} (batch means: {self.n_batches}x{self.batch_size})"
        return head + ("\n  ! " + "\n  ! ".join(self.warnings) if self.warnings else "")


def batch_means(
    series: Iterable[float], n_batches: int = 20, confidence: float = 0.95
) -> BatchMeansResult:
    """Confidence interval for a steady-state mean from ONE long run.

    Successive observations within a run are autocorrelated -- a long queue at
    time t implies a long queue at t+1 -- so treating them as independent samples
    inflates the apparent sample size and shrinks the interval far below the
    truth. Averaging within large batches decorrelates the batch means enough to
    apply the usual t interval.

    Truncate the warm-up period before calling this (see welch_warmup). Checks the
    lag-1 autocorrelation of the batch means and warns when the batches are still
    correlated, which means the batch size is too small.
    """
    x = np.asarray(list(series), dtype=float).ravel()
    if n_batches < 2:
        raise ValueError("need at least 2 batches")
    batch_size = x.size // n_batches
    if batch_size < 2:
        raise ValueError(
            f"series of {x.size} is too short for {n_batches} batches; "
            "shorten the run length or reduce n_batches"
        )
    trimmed = x[: batch_size * n_batches].reshape(n_batches, batch_size)
    means = trimmed.mean(axis=1)
    centered = means - means.mean()
    denom = float((centered ** 2).sum())
    r1 = float((centered[:-1] * centered[1:]).sum() / denom) if denom > 0 else 0.0

    warnings: list[str] = []
    if abs(r1) > 0.2:
        warnings.append(
            f"lag-1 autocorrelation of batch means is {r1:.2f} (>0.2): batches are "
            "still correlated, so this interval is too narrow. Increase run length "
            "or reduce n_batches."
        )
    if batch_size < 20:
        warnings.append(
            f"batch size is only {batch_size}; batches this small rarely decorrelate."
        )
    return BatchMeansResult(
        mc_summary(means, confidence), n_batches, batch_size, r1, tuple(warnings)
    )


def welch_warmup(
    replications: Sequence[Sequence[float]],
    window: int | None = None,
    tol: float = 0.05,
) -> tuple[int, np.ndarray]:
    """Suggest a warm-up truncation point by Welch's procedure.

    A run that starts empty and idle spends its opening stretch below steady state,
    so including it biases every queue statistic downward -- often by more than the
    effect a scenario comparison is trying to detect. Welch's method averages the
    same time index across replications to kill the noise, smooths the result, and
    truncates where it flattens.

    Returns (truncation_index, smoothed_series). "Settled" means the smoothed curve
    stays within `tol` (default 5%) of its terminal level from that point on, with the
    band never tighter than the series' own residual scatter -- otherwise a run with no
    transient at all would be judged never to settle, since pure noise always wanders
    outside a band narrower than itself. Welch's method is graphical by design, so plot
    the returned series and confirm the reading before trusting it. Prefer more
    replications over a longer window; 10 or more replications is the usual guidance.
    """
    y = np.asarray(replications, dtype=float)
    if y.ndim != 2 or y.shape[0] < 2:
        raise ValueError("pass at least 2 replications as a 2-D (replications, time) array")
    averaged = y.mean(axis=0)
    m = averaged.size
    if window is None:
        window = max(1, min(m // 10, 50))
    if window >= m // 2:
        raise ValueError(f"window {window} is too wide for a series of length {m}")

    kernel = np.ones(2 * window + 1) / (2 * window + 1)
    smoothed = np.convolve(averaged, kernel, mode="valid")

    # Terminal segment estimates both the settled level and the stationary scatter
    # around it, so the tolerance band can adapt to how noisy this series actually is.
    tail_start = max(smoothed.size - max(10, smoothed.size // 4), 0)
    terminal = smoothed[tail_start:]
    level = float(terminal.mean())
    scatter = float(terminal.std(ddof=1)) if terminal.size > 1 else 0.0
    band = max(tol * abs(level), 4.0 * scatter)
    if band == 0:  # a perfectly flat series has no transient to find
        return 0, smoothed

    truncation = smoothed.size - 1
    for d in range(smoothed.size):
        if float(np.abs(smoothed[d:] - level).max()) <= band:
            truncation = d
            break
    return int(truncation + window), smoothed


# --------------------------------------------------------------------------- #
# Scenario comparison
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class CRNResult:
    difference: MCSummary
    significant: bool
    variance_reduction: float

    def __str__(self) -> str:
        verdict = "significant" if self.significant else "not distinguishable"
        return (
            f"difference {self.difference} -- {verdict}; "
            f"pairing cut the variance {self.variance_reduction:.1f}x"
        )


def crn_compare(
    baseline: Iterable[float],
    alternative: Iterable[float],
    confidence: float = 0.95,
) -> CRNResult:
    """Paired comparison of two scenarios run on common random numbers.

    Run both scenarios on the same seeds, then compare replication i to replication
    i. Shared noise cancels in the difference, so the interval on the difference can
    be far tighter than either scenario's own interval -- routinely an order of
    magnitude fewer replications for the same resolving power. This is the cheapest
    variance reduction available and it costs only seeding discipline.

    Reports variance_reduction: the ratio of the unpaired variance
    (var_a + var_b) to the paired variance of the differences. A value near 1 means
    the runs were not actually paired -- check that both scenarios drew from
    identically seeded streams and that structural changes did not shift the stream
    alignment.
    """
    a = np.asarray(list(baseline), dtype=float).ravel()
    b = np.asarray(list(alternative), dtype=float).ravel()
    if a.size != b.size:
        raise ValueError(
            f"paired comparison needs equal lengths, got {a.size} and {b.size}; "
            "run both scenarios over the same seeds"
        )
    diff = mc_summary(b - a, confidence)
    unpaired_var = a.var(ddof=1) + b.var(ddof=1)
    paired_var = float((b - a).var(ddof=1))
    reduction = float("inf") if paired_var == 0 else unpaired_var / paired_var
    lo, hi = diff.ci
    return CRNResult(diff, significant=not (lo <= 0.0 <= hi), variance_reduction=reduction)
