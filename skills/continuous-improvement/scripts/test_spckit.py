"""Tests for spckit.

SPC errors are silent -- a wrong constant or the wrong sigma estimate yields a
chart that looks entirely normal and is simply wrong. So these check the numbers
against published references (the Shewhart constant table, the Six Sigma DPMO
table) and against cases with known answers, not merely that the code runs.

    python -m pytest test_spckit.py -q
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import spckit
from spckit import (
    Violation, c_chart, capability, chart_for, constants, dpmo, dpmo_from_sigma,
    first_pass_yield, gage_rr, i_mr, nelson_rules, normal_quantile, normalized_yield,
    np_chart, p_chart, rolled_throughput_yield, sigma_level, u_chart, xbar_r, xbar_s,
)

# Published Shewhart constants (AIAG / Montgomery), n -> (d2, A2, D3, D4, A3, B3, B4, c4)
PUBLISHED = {
    2:  (1.128, 1.880, 0.000, 3.267, 2.659, 0.000, 3.267, 0.7979),
    3:  (1.693, 1.023, 0.000, 2.574, 1.954, 0.000, 2.568, 0.8862),
    4:  (2.059, 0.729, 0.000, 2.282, 1.628, 0.000, 2.266, 0.9213),
    5:  (2.326, 0.577, 0.000, 2.114, 1.427, 0.000, 2.089, 0.9400),
    6:  (2.534, 0.483, 0.000, 2.004, 1.287, 0.030, 1.970, 0.9515),
    7:  (2.704, 0.419, 0.076, 1.924, 1.182, 0.118, 1.882, 0.9594),
    8:  (2.847, 0.373, 0.136, 1.864, 1.099, 0.185, 1.815, 0.9650),
    9:  (2.970, 0.337, 0.184, 1.816, 1.032, 0.239, 1.761, 0.9693),
    10: (3.078, 0.308, 0.223, 1.777, 0.975, 0.284, 1.716, 0.9727),
}


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("n", sorted(PUBLISHED))
def test_derived_constants_match_the_published_table(n):
    d2, A2, D3, D4, A3, B3, B4, c4 = PUBLISHED[n]
    c = constants(n)
    assert c["d2"] == pytest.approx(d2, abs=1e-3)
    assert c["c4"] == pytest.approx(c4, abs=1e-4)
    assert c["A2"] == pytest.approx(A2, abs=1e-3)
    assert c["D3"] == pytest.approx(D3, abs=1e-3)
    assert c["D4"] == pytest.approx(D4, abs=1e-3)
    assert c["A3"] == pytest.approx(A3, abs=1e-3)
    assert c["B3"] == pytest.approx(B3, abs=1e-3)
    assert c["B4"] == pytest.approx(B4, abs=1e-3)


def test_constants_reject_untabulated_subgroup_sizes():
    with pytest.raises(ValueError, match="tabulated range"):
        constants(30)


def test_normal_quantile_fallback_matches_scipy(monkeypatch):
    monkeypatch.setattr(spckit, "_scipy_stats", None)
    assert normal_quantile(0.975) == pytest.approx(1.959964, abs=1e-6)
    assert normal_quantile(1 - 3.4e-6) == pytest.approx(4.5, abs=1e-3)


# --------------------------------------------------------------------------- #
# Variables charts
# --------------------------------------------------------------------------- #

def test_xbar_r_limits_match_the_formula():
    rng = np.random.default_rng(0)
    data = rng.normal(100, 2, size=(25, 5))
    res = xbar_r(data)
    c = constants(5)
    rbar = np.ptp(data, axis=1).mean()
    xbarbar = data.mean(axis=1).mean()
    assert res["xbar"].ucl == pytest.approx(xbarbar + c["A2"] * rbar)
    assert res["xbar"].lcl == pytest.approx(xbarbar - c["A2"] * rbar)
    assert res["r"].ucl == pytest.approx(c["D4"] * rbar)
    assert res["r"].lcl == pytest.approx(c["D3"] * rbar) == 0.0


def test_xbar_r_recovers_the_true_sigma():
    """R-bar/d2 is an unbiased estimate of the within-subgroup sigma."""
    rng = np.random.default_rng(1)
    data = rng.normal(50, 3.0, size=(400, 5))
    rbar = np.ptp(data, axis=1).mean()
    assert rbar / constants(5)["d2"] == pytest.approx(3.0, rel=0.05)


def test_xbar_r_flags_a_shifted_subgroup():
    rng = np.random.default_rng(2)
    data = rng.normal(100, 1, size=(30, 5))
    data[15] += 12          # a large special cause
    res = xbar_r(data)
    assert 15 in res["xbar"].out_of_control
    assert not res["xbar"].in_control


def test_r_chart_catches_a_spread_change_the_xbar_chart_misses():
    """Why the R chart is read first: the mean is unchanged, the spread is not."""
    rng = np.random.default_rng(3)
    data = rng.normal(100, 1, size=(30, 5))
    data[10] = 100 + rng.normal(0, 12, size=5)   # same mean, much wider
    res = xbar_r(data)
    assert 10 in res["r"].out_of_control


def test_xbar_s_agrees_with_xbar_r_on_the_same_stable_data():
    rng = np.random.default_rng(4)
    data = rng.normal(20, 2, size=(50, 8))
    r_res, s_res = xbar_r(data), xbar_s(data)
    assert r_res["xbar"].center == pytest.approx(s_res["xbar"].center)
    assert r_res["xbar"].ucl == pytest.approx(s_res["xbar"].ucl, rel=0.05)


def test_i_mr_uses_moving_range_not_overall_sigma():
    """A drifting series: overall sigma absorbs the drift, MR-bar does not."""
    x = np.arange(50, dtype=float) * 0.5 + 10      # steady upward drift
    res = i_mr(x)
    assert res["i"].sigma == pytest.approx(0.5 / spckit._D2[2], rel=1e-9)
    assert res["i"].sigma < x.std(ddof=1)          # far tighter than the overall std
    assert not res["i"].in_control                 # so the drift is actually caught


def test_i_mr_needs_three_points():
    with pytest.raises(ValueError, match="at least 3"):
        i_mr([1.0, 2.0])


# --------------------------------------------------------------------------- #
# Attribute charts
# --------------------------------------------------------------------------- #

def test_p_chart_limits_vary_with_sample_size():
    res = p_chart([5, 6, 4, 20], [100, 100, 100, 1000])
    assert res.center == pytest.approx(35 / 1300)
    assert res.ucl[3] < res.ucl[0]      # a bigger sample gives tighter limits
    assert any("sample sizes vary" in n for n in res.notes)


def test_p_chart_limits_are_clipped_to_valid_proportions():
    res = p_chart([1, 0, 2], [10, 10, 10])
    assert np.all(res.lcl >= 0.0) and np.all(res.ucl <= 1.0)


def test_p_chart_rejects_impossible_input():
    with pytest.raises(ValueError, match="more defectives than units"):
        p_chart([11], [10])
    with pytest.raises(ValueError, match="same length"):
        p_chart([1, 2], [10])


def test_np_and_c_chart_limits():
    res = np_chart([5, 7, 6, 6], 100)
    pbar = 6 / 100
    assert res.center == pytest.approx(6.0)
    assert res.ucl == pytest.approx(6 + 3 * math.sqrt(100 * pbar * (1 - pbar)))

    res = c_chart([4, 5, 3, 4])
    assert res.center == pytest.approx(4.0)
    assert res.ucl == pytest.approx(4 + 3 * 2.0)
    assert res.lcl == 0.0        # clipped, since 4 - 6 < 0


def test_u_chart_normalises_by_opportunity_size():
    res = u_chart([10, 20], [100, 200])
    assert res.center == pytest.approx(30 / 300)
    assert res.points[0] == pytest.approx(res.points[1])


def test_chart_for_picks_the_right_family():
    assert chart_for("continuous", 1) == "i_mr"
    assert chart_for("continuous", 5) == "xbar_r"
    assert chart_for("continuous", 15) == "xbar_s"
    assert chart_for("defective", varying_size=True) == "p_chart"
    assert chart_for("defective", varying_size=False) == "np_chart"
    assert chart_for("defects", varying_size=True) == "u_chart"
    assert chart_for("defects", varying_size=False) == "c_chart"
    with pytest.raises(ValueError, match="unknown data type"):
        chart_for("vibes")


# --------------------------------------------------------------------------- #
# Nelson rules
# --------------------------------------------------------------------------- #

def rules_hit(points, center=0.0, sigma=1.0) -> set[int]:
    return {v.rule for v in nelson_rules(points, center, sigma)}


def test_a_short_quiet_series_triggers_nothing():
    """No rule can fire on a series too short and too well-behaved to signal."""
    assert rules_hit(np.array([0.3, -0.4, 0.2, -0.1, 0.5, -0.3, 0.1])) == set()


def test_rule_1_false_alarm_rate_matches_theory_on_a_stable_process():
    """P(any point beyond 3 sigma in 40) = 1 - (1 - 0.0027)^40 ~= 10%."""
    rng = np.random.default_rng(99)
    hits = sum(1 in rules_hit(rng.normal(0, 1, size=40)) for _ in range(500))
    assert 0.05 <= hits / 500 <= 0.18


def test_all_eight_rules_together_have_a_substantial_false_alarm_rate():
    """Roughly a third of stable 40-point series signal on *some* rule.

    This is why a signal means investigate, not adjust: testing eight rules at
    once buys sensitivity to drift and stratification at the cost of regular false
    alarms. Reacting to every one of them is tampering, and tampering adds
    variation rather than removing it.
    """
    rng = np.random.default_rng(99)
    hits = sum(bool(rules_hit(rng.normal(0, 1, size=40))) for _ in range(500))
    assert 0.20 <= hits / 500 <= 0.50


def test_rule_1_point_beyond_three_sigma():
    x = np.zeros(20); x[5] = 3.5
    assert 1 in rules_hit(x)


def test_rule_2_nine_on_one_side():
    x = np.concatenate([np.full(9, 0.3), np.full(9, -0.3)])
    hits = rules_hit(x)
    assert 2 in hits


def test_rule_3_six_increasing():
    x = np.array([0, .1, .2, .3, .4, .5, .6, .5, .4, .55, .45, .5])
    assert 3 in rules_hit(x)


def test_rule_4_fourteen_alternating():
    x = np.array([0.2 if i % 2 else -0.2 for i in range(16)])
    assert 4 in rules_hit(x)


def test_rule_5_two_of_three_beyond_two_sigma():
    x = np.zeros(12); x[4] = 2.5; x[5] = 2.4
    assert 5 in rules_hit(x)


def test_rule_5_ignores_opposite_sides():
    """Two points beyond 2 sigma on OPPOSITE sides is not a rule 5 signal."""
    x = np.zeros(12); x[4] = 2.5; x[5] = -2.4
    assert 5 not in rules_hit(x)


def test_rule_6_four_of_five_beyond_one_sigma():
    x = np.zeros(12); x[2:6] = 1.5
    assert 6 in rules_hit(x)


def test_rule_7_fifteen_hugging_the_centreline():
    """Too good to be true: usually stratified subgroups, not a great process."""
    x = np.full(16, 0.1)
    assert 7 in rules_hit(x)


def test_rule_8_eight_outside_one_sigma_both_ways():
    """A mixture of two populations: nothing near the centre."""
    x = np.array([1.5, -1.5] * 5)
    assert 8 in rules_hit(x)


def test_rules_can_be_restricted():
    x = np.zeros(20); x[5] = 3.5
    assert rules_hit(x) >= {1}
    assert {v.rule for v in nelson_rules(x, 0.0, 1.0, rules=[1])} == {1}
    assert nelson_rules(x, 0.0, 1.0, rules=[3]) == []


def test_violation_reports_its_indices():
    x = np.zeros(20); x[5] = 3.5
    v = [v for v in nelson_rules(x, 0.0, 1.0, rules=[1])][0]
    assert isinstance(v, Violation) and v.indices == (5,)
    assert "rule 1" in str(v)


def test_nelson_rejects_nonpositive_sigma():
    with pytest.raises(ValueError, match="sigma must be positive"):
        nelson_rules([1, 2, 3], 0.0, 0.0)


# --------------------------------------------------------------------------- #
# Capability
# --------------------------------------------------------------------------- #

def test_capability_on_a_centred_process_with_known_sigma():
    """mean 10, sigma 1, spec 7-13 => Cp = Cpk = 1.0."""
    rng = np.random.default_rng(11)
    data = rng.normal(10, 1, size=(200, 5))
    data = (data - data.mean()) / data.std(ddof=1) + 10   # force mean 10, sigma 1
    cap = capability(data, lsl=7, usl=13, subgroups=True)
    assert cap.pp == pytest.approx(1.0, abs=0.02)
    assert cap.ppk == pytest.approx(1.0, abs=0.02)


def test_cpk_penalises_an_off_centre_process_while_cp_does_not():
    rng = np.random.default_rng(12)
    x = rng.normal(0, 1, size=2000)
    x = (x - x.mean()) / x.std(ddof=1) + 11        # mean 11, sigma 1
    cap = capability(x, lsl=7, usl=13)
    assert cap.pp == pytest.approx(1.0, abs=0.02)          # spread alone: unchanged
    assert cap.ppk == pytest.approx(2 / 3, abs=0.02)       # centring: penalised
    assert any("off-centre" in w for w in cap.warnings)


def test_one_sided_specification_gives_cpk_but_no_cp():
    rng = np.random.default_rng(13)
    x = rng.normal(10, 1, size=500)
    cap = capability(x, usl=13)
    assert cap.pp is None and cap.ppk is not None
    cap = capability(x, lsl=7)
    assert cap.pp is None and cap.ppk is not None


def test_capability_warns_when_short_term_far_exceeds_long_term():
    """Capable but not controlled: tight subgroups, drifting centre."""
    rng = np.random.default_rng(14)
    subgroups = np.array([rng.normal(10 + 3 * math.sin(i / 4), 0.2, size=5) for i in range(60)])
    cap = capability(subgroups, lsl=0, usl=20, subgroups=True)
    assert cap.cpk > cap.ppk
    assert any("drifting or shifting" in w for w in cap.warnings)


def test_capability_always_warns_about_stability():
    cap = capability(np.random.default_rng(15).normal(10, 1, size=100), lsl=7, usl=13)
    assert any("statistical control" in w for w in cap.warnings)


def test_capability_input_validation():
    x = [1.0, 2.0, 3.0, 4.0]
    with pytest.raises(ValueError, match="at least one specification"):
        capability(x)
    with pytest.raises(ValueError, match="must be below"):
        capability(x, lsl=10, usl=5)
    with pytest.raises(ValueError, match="zero variation"):
        capability([5.0, 5.0, 5.0, 5.0], lsl=1, usl=9)


# --------------------------------------------------------------------------- #
# Defect rates and yield
# --------------------------------------------------------------------------- #

def test_dpmo_arithmetic():
    assert dpmo(3, 1000) == pytest.approx(3000.0)
    assert dpmo(3, 1000, opportunities=3) == pytest.approx(1000.0)
    with pytest.raises(ValueError):
        dpmo(-1, 100)
    with pytest.raises(ValueError):
        dpmo(1, 0)


@pytest.mark.parametrize("dpmo_value,expected", [
    (3.4, 6.0), (233.0, 5.0), (6210.0, 4.0), (66807.0, 3.0), (308537.0, 2.0),
])
def test_sigma_level_matches_the_published_table(dpmo_value, expected):
    assert sigma_level(dpmo_value) == pytest.approx(expected, abs=0.01)


def test_sigma_level_shift_convention_is_explicit():
    """Without the 1.5 shift the same defect rate reports 1.5 sigma lower."""
    assert sigma_level(3.4, shift=0.0) == pytest.approx(4.5, abs=0.01)
    assert sigma_level(3.4) - sigma_level(3.4, shift=0.0) == pytest.approx(1.5)


def test_dpmo_and_sigma_level_are_inverses():
    for s in (3.0, 4.0, 5.0, 6.0):
        assert sigma_level(dpmo_from_sigma(s)) == pytest.approx(s, abs=1e-6)


def test_sigma_level_rejects_out_of_range():
    with pytest.raises(ValueError):
        sigma_level(-1)
    with pytest.raises(ValueError):
        sigma_level(1e6)
    assert sigma_level(0) == float("inf")


def test_rolled_throughput_yield_exposes_the_hidden_factory():
    """Ten healthy-looking steps deliver 60% end to end."""
    rty = rolled_throughput_yield([0.95] * 10)
    assert rty == pytest.approx(0.5987, abs=1e-4)
    assert normalized_yield(rty, 10) == pytest.approx(0.95, abs=1e-6)


def test_first_pass_yield():
    assert first_pass_yield(100, 5) == pytest.approx(0.95)
    with pytest.raises(ValueError):
        first_pass_yield(100, 101)


def test_rty_rejects_percentages():
    with pytest.raises(ValueError, match="fractions"):
        rolled_throughput_yield([95, 98])


# --------------------------------------------------------------------------- #
# Gage R&R
# --------------------------------------------------------------------------- #

def _gage_data(part_sd, repeat_sd, operator_bias_sd, seed, p=10, o=3, r=3):
    rng = np.random.default_rng(seed)
    parts = rng.normal(0, part_sd, size=p)
    bias = rng.normal(0, operator_bias_sd, size=o)
    return (parts[:, None, None] + bias[None, :, None]
            + rng.normal(0, repeat_sd, size=(p, o, r)))


def test_gage_rr_accepts_a_precise_measurement_system():
    res = gage_rr(_gage_data(part_sd=10.0, repeat_sd=0.2, operator_bias_sd=0.1, seed=21))
    assert res.pct_grr < 10
    assert res.ndc >= 5
    assert "acceptable" in res.verdict


def test_gage_rr_rejects_a_system_dominated_by_measurement_error():
    res = gage_rr(_gage_data(part_sd=1.0, repeat_sd=3.0, operator_bias_sd=0.5, seed=22))
    assert res.pct_grr > 30
    assert "UNACCEPTABLE" in res.verdict


def test_gage_rr_separates_operator_bias_from_gauge_noise():
    """Operators disagreeing with each other is reproducibility, not repeatability."""
    biased = gage_rr(_gage_data(part_sd=5.0, repeat_sd=0.2, operator_bias_sd=4.0, seed=23))
    noisy = gage_rr(_gage_data(part_sd=5.0, repeat_sd=4.0, operator_bias_sd=0.2, seed=24))
    assert biased.reproducibility > biased.repeatability
    assert noisy.repeatability > noisy.reproducibility


def test_gage_rr_variance_components_decompose_the_total():
    res = gage_rr(_gage_data(part_sd=5.0, repeat_sd=1.0, operator_bias_sd=1.0, seed=25))
    assert res.total_variation ** 2 == pytest.approx(
        res.grr ** 2 + res.part_variation ** 2, rel=1e-9)
    assert res.grr ** 2 == pytest.approx(
        res.repeatability ** 2 + res.reproducibility ** 2, rel=1e-9)
    assert res.pct_grr ** 2 + res.pct_part ** 2 == pytest.approx(100.0 ** 2, rel=1e-6)


def test_gage_rr_requires_a_crossed_design():
    with pytest.raises(ValueError, match="3-D array"):
        gage_rr(np.zeros((10, 3)))
    with pytest.raises(ValueError, match="at least 2 parts"):
        gage_rr(np.zeros((1, 3, 3)))
