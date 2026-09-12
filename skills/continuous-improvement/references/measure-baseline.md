# Measure: baseline and capability (State 2)

The phase that makes the rest possible. Without a trustworthy baseline there is nothing
to prove a root cause against in State 3 and nothing to demonstrate an improvement
against in State 5, so time spent here is not overhead — it is the evidence.

## Validate the measurement system first

Run this before computing a single capability index. Observed variation is process
variation plus measurement variation, and if the second is large you will spend the
project attacking the first and never move the number.

```python
from spckit import gage_rr
result = gage_rr(measurements)     # 3-D array: (part, operator, replicate)
print(result)                      # %GRR, ndc, verdict
```

AIAG thresholds: **%GRR under 10%** acceptable, 10–30% marginal, **over 30% unacceptable**.
**ndc** (distinct categories the system can resolve) should be 5 or more — below that the
gauge cannot reliably tell your parts apart, so it cannot detect the improvement either.

For software and service processes the "gauge" is usually a timestamp or a definition.
The equivalent checks: do two people classify the same ticket the same way (attribute
agreement), does the clock start at the same event every time, does "closed" mean the same
thing across teams? A category definition that drifts between observers is a failing gauge
even though nothing is being physically measured.

## Data collection plan

Write it down before collecting. Each CTQ needs: operational definition (precise enough
that two people produce the same number), measurement method, sample size, sampling
frequency, stratification factors to capture, and who collects it.

**Stratification factors are the ones people forget**, and they are what State 3 will test:
shift, operator, machine, region, customer segment, product variant, day of week. Capture
them at collection time — you cannot retrofit a factor you did not record, and re-running
the baseline costs a month.

Sample the process as it runs. A "representative week" chosen after the fact is chosen
with knowledge of the outcome, and a baseline starting at an unusually bad week
manufactures an improvement out of regression to the mean.

## Baseline capability

```python
from spckit import capability, dpmo, sigma_level, rolled_throughput_yield

cap = capability(subgrouped_data, lsl=7, usl=13, subgroups=True)
print(cap)                              # Cp, Cpk, Pp, Ppk + warnings

d = dpmo(defects=47, units=2500, opportunities=3)
print(f"{d:.0f} DPMO = {sigma_level(d):.2f} sigma")

rty = rolled_throughput_yield([0.98, 0.95, 0.99, 0.97])
```

### Which index, and why the pairs differ

| Index | Sigma used | Answers |
|---|---|---|
| **Cp** | within-subgroup (short-term) | Could the process fit inside the spec if perfectly centred? |
| **Cpk** | within-subgroup | Does it fit, given where it is actually centred? |
| **Pp** | overall (long-term) | Did the spread actually delivered fit? |
| **Ppk** | overall | Did actual performance fit, as delivered? |

Two gaps carry diagnostic information, and reading them is most of the value:

- **Cp much greater than Cpk** → the process is off-centre. Centring is usually the
  cheapest improvement available, since it needs no variance reduction at all.
- **Cpk much greater than Ppk** → capable short-term, drifting or shifting long-term. The
  problem is *control*, not capability, and buying a better machine will not fix it.

Rules of thumb: Cpk ≥ 1.33 is the usual minimum for a capable process, 1.67 for critical
characteristics, 2.0 is "six sigma". Below 1.0 the process is producing defects as
designed.

**Capability assumes statistical control and approximate normality.** On an out-of-control
process these indices describe a distribution that does not exist — chart first, compute
second. `spckit.capability` always returns that caveat in its warnings for exactly this
reason. For non-normal data, either transform (Box-Cox), fit the appropriate distribution
and compute percentile-based indices, or report the empirical defect rate directly, which
is honest and needs no distributional assumption at all.

## DPMO, sigma level, and yield

- **DPMO** = defects / (units × opportunities) × 1,000,000. *Opportunities* is the number
  of ways one unit can be defective, and it is the lever people quietly pull to improve
  their sigma. Fix its definition in the State 1 charter and never revise it mid-project.
- **Sigma level** conventionally includes a **1.5σ shift** — the assumption that long-term
  performance drifts 1.5σ from short-term. That is why 3.4 DPMO is called "six sigma"
  rather than 4.5. State the convention; `sigma_level(dpmo, shift=0)` gives the unshifted Z.
- **First pass yield** is the fraction through a step with no rework.
- **Rolled throughput yield** is the product of the FPYs — the probability a unit passes
  every step untouched.

RTY is the number that exposes the hidden factory. Ten steps at 95% look healthy one at a
time and deliver 60% end to end; the missing 40% is rework that no step counted as a
defect because each one fixed its own problem. Departmental metrics can all be green while
the customer experience is the RTY.

| Sigma | DPMO | Yield |
|---|---|---|
| 6 | 3.4 | 99.99966% |
| 5 | 233 | 99.977% |
| 4 | 6,210 | 99.38% |
| 3 | 66,807 | 93.3% |
| 2 | 308,537 | 69.1% |

## Value stream map

Map the flow before optimizing any part of it. For each step record process time, wait
time, and first pass yield; then compute **process cycle efficiency** = value-added time /
total lead time. In most unexamined processes this lands between 1% and 10%, which
relocates the opportunity: the win is in the waiting, not in making the working faster.

This is also where the constraint becomes visible. Improving a non-bottleneck step adds
work-in-progress and zero throughput — a real and common way to spend a quarter and move
nothing the customer sees.
