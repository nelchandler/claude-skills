"""Tests for simkit.

These exist so the helpers can be trusted without re-deriving them. They check the
statistics, not just that the code runs: quantiles against published values, interval
coverage against its nominal rate, batch means against a process with known
autocorrelation, and the CRN pairing against a case where the variance reduction is
analytically predictable.

    python -m pytest test_simkit.py -q
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import simkit
from simkit import (
    batch_means,
    bootstrap_ci,
    convergence_trace,
    crn_compare,
    mc_summary,
    n_for_halfwidth,
    normal_quantile,
    rare_event_n,
    seed_streams,
    t_quantile,
    welch_warmup,
)


# --------------------------------------------------------------------------- #
# Quantiles
# --------------------------------------------------------------------------- #

def test_normal_quantile_matches_published_values():
    assert normal_quantile(0.975) == pytest.approx(1.959964, abs=1e-5)
    assert normal_quantile(0.95) == pytest.approx(1.644854, abs=1e-5)
    assert normal_quantile(0.995) == pytest.approx(2.575829, abs=1e-5)
    assert normal_quantile(0.5) == pytest.approx(0.0, abs=1e-9)
    assert normal_quantile(0.025) == pytest.approx(-1.959964, abs=1e-5)


def test_t_quantile_matches_published_values():
    assert t_quantile(0.975, 9) == pytest.approx(2.262157, abs=1e-4)
    assert t_quantile(0.975, 30) == pytest.approx(2.042272, abs=1e-4)
    assert t_quantile(0.95, 19) == pytest.approx(1.729133, abs=1e-4)


def test_quantile_fallback_agrees_with_scipy(monkeypatch):
    """The no-scipy path has to be usable, not merely present."""
    monkeypatch.setattr(simkit, "_scipy_stats", None)
    assert normal_quantile(0.975) == pytest.approx(1.959964, abs=1e-6)
    assert t_quantile(0.975, 9) == pytest.approx(2.262157, abs=1e-3)
    assert t_quantile(0.975, 100) == pytest.approx(1.983972, abs=1e-4)


def test_t_is_wider_than_z_and_converges_to_it():
    assert t_quantile(0.975, 5) > t_quantile(0.975, 50) > normal_quantile(0.975)
    assert t_quantile(0.975, 5000) == pytest.approx(normal_quantile(0.975), abs=1e-3)


def test_quantiles_reject_bad_input():
    with pytest.raises(ValueError):
        normal_quantile(0.0)
    with pytest.raises(ValueError):
        normal_quantile(1.5)
    with pytest.raises(ValueError):
        t_quantile(0.975, 0)


# --------------------------------------------------------------------------- #
# Seeding
# --------------------------------------------------------------------------- #

def test_seed_streams_is_reproducible():
    a = [r.normal(size=5) for r in seed_streams(20260912, n=3)]
    b = [r.normal(size=5) for r in seed_streams(20260912, n=3)]
    for x, y in zip(a, b):
        np.testing.assert_array_equal(x, y)


def test_seed_streams_are_distinct_across_replications():
    draws = [r.normal(size=100) for r in seed_streams(7, n=4)]
    for i in range(len(draws)):
        for j in range(i + 1, len(draws)):
            assert not np.allclose(draws[i], draws[j])


def test_labelled_streams_are_independent_of_draw_order():
    """Adding a draw to one stream must not shift another -- this is why CRN works."""
    s1 = seed_streams(42, labels=["arrivals", "service"])
    s1["arrivals"].exponential(1.0, size=10)  # extra consumption on one stream only
    first_service = s1["service"].exponential(2.0, size=5)

    s2 = seed_streams(42, labels=["arrivals", "service"])
    second_service = s2["service"].exponential(2.0, size=5)

    np.testing.assert_array_equal(first_service, second_service)


def test_seed_streams_requires_exactly_one_mode():
    with pytest.raises(ValueError):
        seed_streams(1)
    with pytest.raises(ValueError):
        seed_streams(1, n=2, labels=["a"])


# --------------------------------------------------------------------------- #
# Intervals and sizing
# --------------------------------------------------------------------------- #

def test_mc_summary_arithmetic():
    s = mc_summary([1.0, 2.0, 3.0, 4.0, 5.0], confidence=0.95)
    assert s.n == 5
    assert s.mean == pytest.approx(3.0)
    assert s.std == pytest.approx(math.sqrt(2.5))
    assert s.stderr == pytest.approx(math.sqrt(2.5) / math.sqrt(5))
    assert s.half_width == pytest.approx(t_quantile(0.975, 4) * s.stderr)
    lo, hi = s.ci
    assert lo < 3.0 < hi
    assert s.relative_half_width == pytest.approx(s.half_width / 3.0)


def test_mc_summary_interval_covers_the_truth_at_its_nominal_rate():
    rng = np.random.default_rng(11)
    covered = sum(
        1
        for _ in range(4000)
        if (lambda ci: ci[0] <= 0.0 <= ci[1])(mc_summary(rng.normal(size=12)).ci)
    )
    assert 0.93 <= covered / 4000 <= 0.97


def test_mc_summary_needs_two_observations():
    with pytest.raises(ValueError):
        mc_summary([1.0])


def test_n_for_halfwidth_scales_quadratically_with_precision():
    rng = np.random.default_rng(3)
    pilot = rng.normal(loc=10.0, scale=2.0, size=40)
    coarse = n_for_halfwidth(pilot, 1.0)
    fine = n_for_halfwidth(pilot, 0.5)
    assert fine == pytest.approx(4 * coarse, rel=0.1)


def test_n_for_halfwidth_recovers_a_known_variance():
    """sigma=2, half-width=0.5 at 95% implies n ~= (1.96*2/0.5)^2 ~= 62."""
    rng = np.random.default_rng(5)
    pilot = rng.normal(loc=0.0, scale=2.0, size=2000)
    assert n_for_halfwidth(pilot, 0.5) == pytest.approx(62, rel=0.1)


def test_n_for_halfwidth_relative_mode():
    rng = np.random.default_rng(9)
    pilot = rng.normal(loc=100.0, scale=10.0, size=200)
    assert n_for_halfwidth(pilot, 0.01, relative=True) == pytest.approx(
        n_for_halfwidth(pilot, 1.0), rel=0.05
    )


def test_n_for_halfwidth_rejects_nonpositive_target():
    with pytest.raises(ValueError):
        n_for_halfwidth([1.0, 2.0, 3.0], 0.0)


def test_rare_event_n_scales_inversely_with_probability():
    assert rare_event_n(1e-2) == pytest.approx(rare_event_n(1e-1) * 10, rel=0.15)
    assert rare_event_n(1e-4) > 3_000_000  # brute force is not viable down here
    with pytest.raises(ValueError):
        rare_event_n(0.0)


def test_bootstrap_ci_brackets_a_known_percentile():
    rng = np.random.default_rng(2)
    x = rng.normal(loc=0.0, scale=1.0, size=800)
    point, (lo, hi) = bootstrap_ci(
        x, statistic=lambda a: float(np.quantile(a, 0.95)), resamples=2000, rng=rng
    )
    assert lo <= point <= hi
    assert lo <= 1.645 <= hi  # true 95th percentile of a standard normal


def test_convergence_trace_intervals_shrink():
    rng = np.random.default_rng(4)
    trace = convergence_trace(rng.normal(size=500), points=10)
    assert trace[0][0] < trace[-1][0] == 500
    assert trace[-1][2] < trace[0][2]


# --------------------------------------------------------------------------- #
# Steady-state analysis
# --------------------------------------------------------------------------- #

def _ar1(n: int, phi: float, rng: np.random.Generator) -> np.ndarray:
    """AR(1): x_t = phi*x_{t-1} + eps. Strongly autocorrelated, mean 0."""
    eps = rng.normal(size=n)
    x = np.empty(n)
    x[0] = eps[0]
    for t in range(1, n):
        x[t] = phi * x[t - 1] + eps[t]
    return x


def test_batch_means_is_wider_than_the_naive_interval_on_correlated_data():
    """The naive interval on an autocorrelated series is the classic overclaim."""
    rng = np.random.default_rng(1)
    series = _ar1(20_000, phi=0.9, rng=rng)
    naive = mc_summary(series)
    batched = batch_means(series, n_batches=20)
    assert batched.summary.half_width > 3 * naive.half_width


def test_batch_means_covers_the_true_mean_of_an_ar1_process():
    rng = np.random.default_rng(6)
    hits = 0
    for _ in range(200):
        lo, hi = batch_means(_ar1(20_000, 0.8, rng), n_batches=20).summary.ci
        hits += lo <= 0.0 <= hi
    assert hits / 200 >= 0.88  # nominal 95%, some undercoverage is expected


def test_batch_means_warns_when_batches_stay_correlated():
    rng = np.random.default_rng(8)
    result = batch_means(_ar1(400, phi=0.98, rng=rng), n_batches=20)
    assert result.batch_size == 20
    assert result.warnings  # too-short batches on a very sticky process
    assert "autocorrelation" in str(result) or "batch size" in str(result)


def test_batch_means_rejects_a_series_too_short_to_batch():
    with pytest.raises(ValueError):
        batch_means(np.arange(10.0), n_batches=20)
    with pytest.raises(ValueError):
        batch_means(np.arange(100.0), n_batches=1)


def test_welch_warmup_finds_a_transient():
    """A run that ramps for 200 steps then flattens should truncate inside the ramp."""
    rng = np.random.default_rng(12)
    t = np.arange(1000)
    mean_path = 10.0 * (1.0 - np.exp(-t / 60.0))  # settles by ~t=300
    reps = np.array([mean_path + rng.normal(scale=0.5, size=t.size) for _ in range(20)])
    truncation, smoothed = welch_warmup(reps, window=25)
    assert 50 <= truncation <= 500
    assert smoothed.size < t.size


def test_welch_warmup_truncates_early_when_there_is_no_transient():
    rng = np.random.default_rng(13)
    reps = np.array([rng.normal(loc=5.0, scale=1.0, size=1000) for _ in range(20)])
    truncation, _ = welch_warmup(reps, window=25)
    assert truncation < 300


def test_welch_warmup_validates_shape_and_window():
    with pytest.raises(ValueError):
        welch_warmup(np.arange(10.0).reshape(1, 10))
    with pytest.raises(ValueError):
        welch_warmup(np.zeros((3, 20)), window=15)


# --------------------------------------------------------------------------- #
# Scenario comparison
# --------------------------------------------------------------------------- #

def test_crn_compare_detects_a_small_shift_that_unpaired_runs_would_miss():
    """Shared noise cancels in the difference; that is the whole point of CRN."""
    rng = np.random.default_rng(14)
    shared = rng.normal(scale=10.0, size=30)  # big common variation
    baseline = shared + rng.normal(scale=0.1, size=30)
    alternative = shared + 0.5 + rng.normal(scale=0.1, size=30)

    result = crn_compare(baseline, alternative)
    assert result.difference.mean == pytest.approx(0.5, abs=0.1)
    assert result.significant
    assert result.variance_reduction > 100

    # The same 0.5 shift is invisible without pairing.
    unpaired = mc_summary(alternative)
    assert unpaired.half_width > 0.5


def test_crn_compare_reports_no_reduction_when_runs_are_not_paired():
    rng = np.random.default_rng(15)
    a = rng.normal(scale=10.0, size=200)
    b = rng.normal(scale=10.0, size=200)
    result = crn_compare(a, b)
    assert result.variance_reduction == pytest.approx(1.0, abs=0.25)
    assert not result.significant


def test_crn_compare_requires_equal_lengths():
    with pytest.raises(ValueError, match="same seeds"):
        crn_compare([1.0, 2.0, 3.0], [1.0, 2.0])
