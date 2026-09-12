"""spckit -- the calculations a DMAIC project repeats.

Control chart limits, Nelson rules, process capability, defect rates, yield, and
measurement system analysis. These are worth having in one tested place because
the failure mode is silent: a transcribed control chart constant, a Cpk computed
against overall rather than within-subgroup sigma, or a sigma level missing the
1.5-shift convention all produce a plausible number that is simply wrong, and
nothing downstream complains.

Depends on NumPy. Uses scipy.stats for the normal quantile when installed and
falls back to Acklam's approximation otherwise, so it works in a bare
environment. (That fallback is duplicated from simkit rather than imported --
skills are installed independently and must not depend on each other's files.)

    from spckit import xbar_r, i_mr, p_chart, nelson_rules, capability, sigma_level
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np

try:
    from scipy import stats as _scipy_stats
except ImportError:  # pragma: no cover - exercised by the no-scipy test
    _scipy_stats = None

__all__ = [
    "constants", "ChartResult", "xbar_r", "xbar_s", "i_mr",
    "p_chart", "np_chart", "c_chart", "u_chart", "chart_for",
    "nelson_rules", "Violation",
    "Capability", "capability",
    "dpmo", "sigma_level", "dpmo_from_sigma",
    "first_pass_yield", "rolled_throughput_yield", "normalized_yield",
    "GageRR", "gage_rr", "normal_quantile",
]


# --------------------------------------------------------------------------- #
# Normal quantile
# --------------------------------------------------------------------------- #

_ACKLAM_A = (-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
             1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00)
_ACKLAM_B = (-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
             6.680131188771972e01, -1.328068155288572e01)
_ACKLAM_C = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
             -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00)
_ACKLAM_D = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
             3.754408661907416e00)


def normal_quantile(p: float) -> float:
    """Inverse standard normal CDF."""
    if not 0.0 < p < 1.0:
        raise ValueError(f"p must be in (0, 1), got {p}")
    if _scipy_stats is not None:
        return float(_scipy_stats.norm.ppf(p))
    a, b, c, d = _ACKLAM_A, _ACKLAM_B, _ACKLAM_C, _ACKLAM_D
    p_low = 0.02425
    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0)
    if p <= 1.0 - p_low:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1.0)
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0)


# --------------------------------------------------------------------------- #
# Control chart constants
# --------------------------------------------------------------------------- #

# d2 and d3 are the mean and standard deviation of the range of n standard
# normals. They have no closed form, so they are tabulated. c4 does have one and
# is computed, which avoids a transcription error in the value that scales every
# X-bar/S limit.
_D2 = {2: 1.128379, 3: 1.692569, 4: 2.058751, 5: 2.325929, 6: 2.534413,
       7: 2.704357, 8: 2.847201, 9: 2.970026, 10: 3.077505, 11: 3.172873,
       12: 3.258460, 13: 3.335980, 14: 3.406763, 15: 3.471828}
_D3 = {2: 0.852502, 3: 0.888368, 4: 0.879808, 5: 0.864082, 6: 0.848040,
       7: 0.833205, 8: 0.819831, 9: 0.807834, 10: 0.797051, 11: 0.787315,
       12: 0.778462, 13: 0.770362, 14: 0.762915, 15: 0.756029}


def _c4(n: int) -> float:
    """E[s]/sigma for a sample of n. Exact: sqrt(2/(n-1)) * Gamma(n/2)/Gamma((n-1)/2)."""
    return math.sqrt(2.0 / (n - 1)) * math.exp(
        math.lgamma(n / 2.0) - math.lgamma((n - 1) / 2.0)
    )


def constants(n: int) -> dict[str, float]:
    """Shewhart constants for subgroup size n, derived from d2, d3 and c4.

    Deriving them rather than tabulating each one means the relationships hold by
    construction: A2 = 3/(d2*sqrt(n)) and so on. The tests check the derived
    values against the published table.
    """
    if n not in _D2:
        raise ValueError(
            f"subgroup size {n} outside the tabulated range 2-15. "
            "Larger subgroups are unusual; use X-bar/S, whose constants are exact."
        )
    d2, d3, c4 = _D2[n], _D3[n], _c4(n)
    root = math.sqrt(1.0 - c4 * c4) / c4
    return {
        "d2": d2, "d3": d3, "c4": c4,
        "A2": 3.0 / (d2 * math.sqrt(n)),
        "D3": max(0.0, 1.0 - 3.0 * d3 / d2),
        "D4": 1.0 + 3.0 * d3 / d2,
        "A3": 3.0 / (c4 * math.sqrt(n)),
        "B3": max(0.0, 1.0 - 3.0 * root),
        "B4": 1.0 + 3.0 * root,
    }


# --------------------------------------------------------------------------- #
# Charts
# --------------------------------------------------------------------------- #

@dataclass
class ChartResult:
    chart: str
    points: np.ndarray
    center: float
    ucl: float | np.ndarray
    lcl: float | np.ndarray
    sigma: float | None = None
    notes: tuple[str, ...] = field(default=())

    @property
    def out_of_control(self) -> np.ndarray:
        """Indices of points beyond the limits (Nelson rule 1)."""
        return np.flatnonzero((self.points > self.ucl) | (self.points < self.lcl))

    @property
    def in_control(self) -> bool:
        return self.out_of_control.size == 0

    def __str__(self) -> str:
        ucl = self.ucl if np.isscalar(self.ucl) else "varies"
        lcl = self.lcl if np.isscalar(self.lcl) else "varies"
        state = "in control" if self.in_control else f"{self.out_of_control.size} point(s) beyond limits"
        head = f"{self.chart}: center={self.center:.4g} UCL={ucl if isinstance(ucl,str) else f'{ucl:.4g}'} " \
               f"LCL={lcl if isinstance(lcl,str) else f'{lcl:.4g}'} -- {state}"
        return head + ("".join(f"\n  note: {n}" for n in self.notes) if self.notes else "")


def _subgroups(data) -> np.ndarray:
    a = np.asarray(data, dtype=float)
    if a.ndim != 2 or a.shape[0] < 2:
        raise ValueError("pass at least 2 subgroups as a 2-D (subgroups, size) array")
    return a


def xbar_r(data) -> dict[str, ChartResult]:
    """X-bar and R charts for subgrouped variable data (subgroup size 2-10ish).

    Read the R chart FIRST. The X-bar limits are computed from R-bar, so if the
    spread is unstable the X-bar limits are meaningless -- a common way to chase
    phantom mean shifts.
    """
    a = _subgroups(data)
    k, n = a.shape
    c = constants(n)
    means, ranges = a.mean(axis=1), np.ptp(a, axis=1)
    xbarbar, rbar = float(means.mean()), float(ranges.mean())
    sigma_within = rbar / c["d2"]
    return {
        "r": ChartResult("R", ranges, rbar, c["D4"] * rbar, c["D3"] * rbar,
                         notes=("read this chart before the X-bar chart",)),
        "xbar": ChartResult("X-bar", means, xbarbar,
                            xbarbar + c["A2"] * rbar, xbarbar - c["A2"] * rbar,
                            sigma=sigma_within / math.sqrt(n),
                            notes=(f"within-subgroup sigma = R-bar/d2 = {sigma_within:.4g}",)),
    }


def xbar_s(data) -> dict[str, ChartResult]:
    """X-bar and S charts. Prefer over X-bar/R when the subgroup size exceeds ~10,
    where the range wastes information relative to the standard deviation."""
    a = _subgroups(data)
    k, n = a.shape
    c = constants(n) if n in _D2 else {"c4": _c4(n)}
    c4 = c["c4"]
    root = math.sqrt(1.0 - c4 * c4) / c4
    A3, B3, B4 = 3.0 / (c4 * math.sqrt(n)), max(0.0, 1.0 - 3.0 * root), 1.0 + 3.0 * root
    means, sds = a.mean(axis=1), a.std(axis=1, ddof=1)
    xbarbar, sbar = float(means.mean()), float(sds.mean())
    sigma_within = sbar / c4
    return {
        "s": ChartResult("S", sds, sbar, B4 * sbar, B3 * sbar,
                         notes=("read this chart before the X-bar chart",)),
        "xbar": ChartResult("X-bar", means, xbarbar,
                            xbarbar + A3 * sbar, xbarbar - A3 * sbar,
                            sigma=sigma_within / math.sqrt(n),
                            notes=(f"within-subgroup sigma = S-bar/c4 = {sigma_within:.4g}",)),
    }


def i_mr(values) -> dict[str, ChartResult]:
    """Individuals and moving-range charts, for one measurement per time period.

    Sigma comes from the average moving range (MR-bar/1.128), not the standard
    deviation of all the values. That matters: the overall standard deviation
    absorbs any drift or shift into the limits themselves, so a drifting process
    ends up with limits wide enough to look stable.
    """
    x = np.asarray(list(values), dtype=float).ravel()
    if x.size < 3:
        raise ValueError("need at least 3 individual values")
    mr = np.abs(np.diff(x))
    mrbar = float(mr.mean())
    sigma = mrbar / _D2[2]
    return {
        "mr": ChartResult("MR", mr, mrbar, 3.267 * mrbar, 0.0),
        "i": ChartResult("Individuals", x, float(x.mean()),
                         x.mean() + 3 * sigma, x.mean() - 3 * sigma, sigma=sigma,
                         notes=(f"sigma from MR-bar/d2 = {sigma:.4g}, not the overall std",)),
    }


def p_chart(defectives, sizes) -> ChartResult:
    """Proportion defective, with limits that vary when the sample sizes do."""
    d = np.asarray(list(defectives), dtype=float)
    n = np.asarray(list(sizes), dtype=float)
    if d.shape != n.shape:
        raise ValueError("defectives and sizes must be the same length")
    if np.any(d > n):
        raise ValueError("a subgroup has more defectives than units")
    pbar = float(d.sum() / n.sum())
    se = np.sqrt(pbar * (1.0 - pbar) / n)
    notes = ()
    if n.std() > 0:
        notes = ("sample sizes vary, so the limits do too; zone-based Nelson rules "
                 "(2 and 5-8) assume constant limits and should not be applied",)
    if np.any(n * pbar < 5):
        notes += ("some subgroups have fewer than ~5 expected defectives; the normal "
                  "approximation behind these limits is poor there",)
    return ChartResult("p", d / n, pbar,
                       np.minimum(1.0, pbar + 3 * se), np.maximum(0.0, pbar - 3 * se),
                       notes=notes)


def np_chart(defectives, size: int) -> ChartResult:
    """Count of defective units, constant sample size."""
    d = np.asarray(list(defectives), dtype=float)
    pbar = float(d.mean() / size)
    se = math.sqrt(size * pbar * (1.0 - pbar))
    return ChartResult("np", d, size * pbar,
                       size * pbar + 3 * se, max(0.0, size * pbar - 3 * se), sigma=se)


def c_chart(counts) -> ChartResult:
    """Count of defects per unit, constant opportunity size (Poisson)."""
    c = np.asarray(list(counts), dtype=float)
    cbar = float(c.mean())
    se = math.sqrt(cbar)
    return ChartResult("c", c, cbar, cbar + 3 * se, max(0.0, cbar - 3 * se), sigma=se)


def u_chart(counts, sizes) -> ChartResult:
    """Defects per unit, varying opportunity size."""
    c = np.asarray(list(counts), dtype=float)
    n = np.asarray(list(sizes), dtype=float)
    if c.shape != n.shape:
        raise ValueError("counts and sizes must be the same length")
    ubar = float(c.sum() / n.sum())
    se = np.sqrt(ubar / n)
    notes = ("sample sizes vary, so the limits do too; zone-based Nelson rules "
             "should not be applied",) if n.std() > 0 else ()
    return ChartResult("u", c / n, ubar, ubar + 3 * se, np.maximum(0.0, ubar - 3 * se),
                       notes=notes)


def chart_for(data_type: str, subgroup_size: int = 1, varying_size: bool = False) -> str:
    """Recommend a chart. Picking the wrong family is the most common SPC error:
    attribute data on a variables chart gives limits that bear no relation to the
    underlying binomial or Poisson spread."""
    t = data_type.lower()
    if t in ("continuous", "variable", "measurement"):
        if subgroup_size <= 1:
            return "i_mr"
        return "xbar_s" if subgroup_size > 10 else "xbar_r"
    if t in ("defective", "proportion", "pass_fail", "binary"):
        return "p_chart" if varying_size else "np_chart"
    if t in ("defects", "count", "occurrences"):
        return "u_chart" if varying_size else "c_chart"
    raise ValueError(
        f"unknown data type '{data_type}'. Use 'continuous', 'defective' "
        "(units pass or fail) or 'defects' (count per unit)."
    )


# --------------------------------------------------------------------------- #
# Nelson rules
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Violation:
    rule: int
    description: str
    indices: tuple[int, ...]

    def __str__(self) -> str:
        return f"rule {self.rule}: {self.description} at points {list(self.indices)}"


_RULE_TEXT = {
    1: "1 point beyond 3 sigma",
    2: "9 points in a row on the same side of centre",
    3: "6 points in a row steadily increasing or decreasing",
    4: "14 points in a row alternating up and down",
    5: "2 of 3 consecutive points beyond 2 sigma on the same side",
    6: "4 of 5 consecutive points beyond 1 sigma on the same side",
    7: "15 points in a row within 1 sigma of centre",
    8: "8 points in a row beyond 1 sigma on either side",
}


def nelson_rules(points, center: float, sigma: float,
                 rules: Sequence[int] | None = None) -> list[Violation]:
    """Detect the 8 Nelson out-of-control signals.

    Rule 1 catches the obvious; the rest catch a process that is drifting,
    cycling or stratified while every individual point sits inside the limits --
    which is exactly the situation a chart is worth having for. Rules 7 and 8 in
    particular usually mean the subgrouping is wrong (7: limits too wide, often
    stratified subgroups; 8: mixture of two populations) rather than the process
    having changed.

    Each rule tested independently raises the false-alarm rate, so on a stable
    process expect an occasional signal. Investigate, don't tamper.
    """
    x = np.asarray(list(points), dtype=float).ravel()
    if sigma <= 0:
        raise ValueError("sigma must be positive")
    wanted = set(rules) if rules is not None else set(_RULE_TEXT)
    z = (x - center) / sigma
    n = x.size
    found: list[Violation] = []

    def add(rule: int, idx: Iterable[int]):
        found.append(Violation(rule, _RULE_TEXT[rule], tuple(int(i) for i in idx)))

    if 1 in wanted:
        for i in np.flatnonzero(np.abs(z) > 3):
            add(1, [i])
    if 2 in wanted:
        for i in range(n - 8):
            w = z[i:i + 9]
            if np.all(w > 0) or np.all(w < 0):
                add(2, range(i, i + 9))
    if 3 in wanted:
        for i in range(n - 6):
            d = np.diff(x[i:i + 7])
            if np.all(d > 0) or np.all(d < 0):
                add(3, range(i, i + 7))
    if 4 in wanted:
        for i in range(n - 13):
            d = np.diff(x[i:i + 14])
            if np.all(d[:-1] * d[1:] < 0):
                add(4, range(i, i + 14))
    if 5 in wanted:
        for i in range(n - 2):
            w = z[i:i + 3]
            for sign in (1, -1):
                if np.sum(sign * w > 2) >= 2:
                    add(5, range(i, i + 3))
                    break
    if 6 in wanted:
        for i in range(n - 4):
            w = z[i:i + 5]
            for sign in (1, -1):
                if np.sum(sign * w > 1) >= 4:
                    add(6, range(i, i + 5))
                    break
    if 7 in wanted:
        for i in range(n - 14):
            if np.all(np.abs(z[i:i + 15]) < 1):
                add(7, range(i, i + 15))
    if 8 in wanted:
        for i in range(n - 7):
            if np.all(np.abs(z[i:i + 8]) > 1):
                add(8, range(i, i + 8))
    return found


# --------------------------------------------------------------------------- #
# Capability
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Capability:
    cp: float | None
    cpk: float | None
    pp: float | None
    ppk: float | None
    mean: float
    sigma_within: float | None
    sigma_overall: float
    warnings: tuple[str, ...] = field(default=())

    def __str__(self) -> str:
        def f(v):
            return "n/a" if v is None else f"{v:.3f}"
        head = (f"Cp={f(self.cp)} Cpk={f(self.cpk)} | Pp={f(self.pp)} Ppk={f(self.ppk)} "
                f"(mean={self.mean:.4g})")
        return head + "".join(f"\n  ! {w}" for w in self.warnings)


def capability(data, lsl: float | None = None, usl: float | None = None,
               subgroups: bool = False) -> Capability:
    """Process capability indices.

    Cp/Cpk use WITHIN-subgroup sigma (short-term, what the process could do);
    Pp/Ppk use OVERALL sigma (long-term, what it actually delivered). A large gap
    between them is itself the finding: the process is capable but not controlled,
    so the improvement is stability, not a tighter machine.

    Cp and Pp ignore centring; Cpk and Ppk do not. Reporting Cp alone on an
    off-centre process is the classic way to overstate capability.

    Pass a 2-D (subgroups, size) array with subgroups=True to get the within
    estimate; a 1-D series gives Pp/Ppk only, unless an I-MR moving range is used
    for the within estimate.
    """
    if lsl is None and usl is None:
        raise ValueError("give at least one specification limit")
    if lsl is not None and usl is not None and lsl >= usl:
        raise ValueError(f"LSL {lsl} must be below USL {usl}")

    warnings: list[str] = [
        "capability assumes the process is in statistical control and roughly "
        "normal -- chart it first; on an unstable process these indices describe "
        "a distribution that does not exist"
    ]

    if subgroups:
        a = _subgroups(data)
        flat = a.ravel()
        n = a.shape[1]
        sigma_within = float(np.ptp(a, axis=1).mean() / _D2[n]) if n in _D2 else \
            float(a.std(axis=1, ddof=1).mean() / _c4(n))
    else:
        flat = np.asarray(list(data), dtype=float).ravel()
        if flat.size < 3:
            raise ValueError("need at least 3 observations")
        sigma_within = float(np.abs(np.diff(flat)).mean() / _D2[2])
        warnings.append("within-subgroup sigma estimated from the moving range of an "
                        "unsubgrouped series")

    mean = float(flat.mean())
    sigma_overall = float(flat.std(ddof=1))
    if sigma_overall <= 0:
        raise ValueError("zero variation: capability is undefined")

    def indices(sigma):
        if sigma is None or sigma <= 0:
            return None, None
        both = lsl is not None and usl is not None
        cp = (usl - lsl) / (6.0 * sigma) if both else None
        sides = []
        if usl is not None:
            sides.append((usl - mean) / (3.0 * sigma))
        if lsl is not None:
            sides.append((mean - lsl) / (3.0 * sigma))
        return cp, min(sides)

    cp, cpk = indices(sigma_within)
    pp, ppk = indices(sigma_overall)

    if cpk is not None and ppk is not None and ppk > 0 and cpk / ppk > 1.33:
        warnings.append(f"Cpk ({cpk:.2f}) far exceeds Ppk ({ppk:.2f}): the process is "
                        "capable short-term but drifting or shifting over time -- "
                        "the problem is control, not capability")
    if cp is not None and cpk is not None and cp - cpk > 0.2:
        warnings.append(f"Cp ({cp:.2f}) exceeds Cpk ({cpk:.2f}): the process is "
                        "off-centre, so centring it gains capability for free")
    return Capability(cp, cpk, pp, ppk, mean, sigma_within, sigma_overall, tuple(warnings))


# --------------------------------------------------------------------------- #
# Defect rates and yield
# --------------------------------------------------------------------------- #

def dpmo(defects: float, units: float, opportunities: int = 1) -> float:
    """Defects per million opportunities.

    'Opportunities' is the count of ways one unit can be defective, and it is the
    number people quietly inflate to improve their sigma level. Define it once,
    in the charter, and keep it fixed.
    """
    if units <= 0 or opportunities <= 0:
        raise ValueError("units and opportunities must be positive")
    if defects < 0:
        raise ValueError("defects cannot be negative")
    return defects / (units * opportunities) * 1e6


def sigma_level(dpmo_value: float, shift: float = 1.5) -> float:
    """Process sigma from DPMO, using the conventional 1.5-sigma shift.

    The shift is a convention, not a measurement: it assumes long-term performance
    drifts 1.5 sigma from short-term, so 3.4 DPMO is reported as 6 sigma rather
    than 4.5. Say which convention you used, since a "4 sigma process" means two
    different defect rates depending on it (pass shift=0 for the unshifted Z).
    """
    if not 0.0 <= dpmo_value < 1e6:
        raise ValueError(f"dpmo must be in [0, 1e6), got {dpmo_value}")
    if dpmo_value == 0:
        return float("inf")
    return normal_quantile(1.0 - dpmo_value / 1e6) + shift


def dpmo_from_sigma(sigma: float, shift: float = 1.5) -> float:
    """Inverse of sigma_level, for setting a target defect rate from a sigma goal."""
    z = sigma - shift
    if _scipy_stats is not None:
        return float((1.0 - _scipy_stats.norm.cdf(z)) * 1e6)
    return (1.0 - 0.5 * math.erfc(-z / math.sqrt(2.0))) * 1e6


def first_pass_yield(units: float, defective_units: float) -> float:
    """Fraction of units through a step with no rework."""
    if units <= 0:
        raise ValueError("units must be positive")
    if not 0 <= defective_units <= units:
        raise ValueError("defective_units must be between 0 and units")
    return (units - defective_units) / units


def rolled_throughput_yield(step_yields: Iterable[float]) -> float:
    """Probability a unit passes every step with no rework: the product of the FPYs.

    This is the number that exposes the hidden factory. Ten steps at 95% each look
    healthy one at a time and deliver 60% end to end, and the missing 40% is rework
    nobody counted as a defect.
    """
    y = [float(v) for v in step_yields]
    if not y:
        raise ValueError("need at least one step yield")
    if any(not 0.0 <= v <= 1.0 for v in y):
        raise ValueError("yields must be fractions in [0, 1], not percentages")
    return float(np.prod(y))


def normalized_yield(rty: float, n_steps: int) -> float:
    """The uniform per-step yield that would give this RTY -- an average step."""
    if not 0.0 < rty <= 1.0 or n_steps < 1:
        raise ValueError("rty must be in (0, 1] and n_steps >= 1")
    return rty ** (1.0 / n_steps)


# --------------------------------------------------------------------------- #
# Measurement system analysis
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class GageRR:
    repeatability: float
    reproducibility: float
    grr: float
    part_variation: float
    total_variation: float
    pct_grr: float
    pct_part: float
    ndc: int
    verdict: str

    def __str__(self) -> str:
        return (f"%GRR={self.pct_grr:.1f}% (repeatability {self.repeatability:.4g}, "
                f"reproducibility {self.reproducibility:.4g}), ndc={self.ndc} -- {self.verdict}")


def gage_rr(measurements) -> GageRR:
    """Crossed Gage R&R by the ANOVA method.

    Pass a 3-D array indexed (part, operator, replicate): every operator measures
    every part several times. Splits the observed variation into repeatability
    (the gauge disagreeing with itself), reproducibility (operators disagreeing
    with each other) and genuine part-to-part variation.

    Do this in State 2, before trusting any baseline. If %GRR is 40%, nearly half
    the "process variation" being attacked is the measuring, and every capability
    number and hypothesis test downstream inherits that error. AIAG guidance:
    under 10% acceptable, 10-30% marginal, over 30% unacceptable; ndc (distinct
    categories the system can tell apart) should be 5 or more.
    """
    a = np.asarray(measurements, dtype=float)
    if a.ndim != 3:
        raise ValueError("pass a 3-D array indexed (part, operator, replicate)")
    p, o, r = a.shape
    if p < 2 or o < 2 or r < 2:
        raise ValueError("need at least 2 parts, 2 operators and 2 replicates")

    grand = a.mean()
    part_means = a.mean(axis=(1, 2))
    oper_means = a.mean(axis=(0, 2))
    cell_means = a.mean(axis=2)

    ss_part = o * r * np.sum((part_means - grand) ** 2)
    ss_oper = p * r * np.sum((oper_means - grand) ** 2)
    ss_inter = r * np.sum((cell_means - part_means[:, None] - oper_means[None, :] + grand) ** 2)
    ss_err = np.sum((a - cell_means[:, :, None]) ** 2)

    ms_part = ss_part / (p - 1)
    ms_oper = ss_oper / (o - 1)
    ms_inter = ss_inter / ((p - 1) * (o - 1))
    ms_err = ss_err / (p * o * (r - 1))

    # Negative variance components are set to zero, as AIAG prescribes -- they mean
    # the term is indistinguishable from noise, not that variance is negative.
    v_rep = max(ms_err, 0.0)
    v_inter = max((ms_inter - ms_err) / r, 0.0)
    v_oper = max((ms_oper - ms_inter) / (p * r), 0.0)
    v_part = max((ms_part - ms_inter) / (o * r), 0.0)

    repeat = math.sqrt(v_rep)
    reprod = math.sqrt(v_oper + v_inter)
    grr = math.sqrt(v_rep + v_oper + v_inter)
    pv = math.sqrt(v_part)
    total = math.sqrt(v_rep + v_oper + v_inter + v_part)

    pct_grr = 100.0 * grr / total if total > 0 else 100.0
    pct_part = 100.0 * pv / total if total > 0 else 0.0
    ndc = int(math.floor(1.41 * pv / grr)) if grr > 0 else 999
    verdict = ("acceptable" if pct_grr < 10 else
               "marginal, improve if practical" if pct_grr < 30 else
               "UNACCEPTABLE: fix the measurement system before trusting any baseline")
    if ndc < 5:
        verdict += f" (ndc={ndc} < 5: cannot reliably distinguish parts)"
    return GageRR(repeat, reprod, grr, pv, total, pct_grr, pct_part, ndc, verdict)
