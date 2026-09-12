# Discrete-event simulation with simpy (States 4–5)

Use DES when entities compete for scarce resources and time advances from one event to
the next. The defining question it answers well: what happens to wait, utilization, and
throughput when demand, capacity, or routing changes.

## Structure that survives contact with State 7

Separate the model from the experiment. State 7 will run this hundreds of times across
seeds and scenarios, so the run function must be pure: parameters and a seed in,
results out, no globals, no printing, no module-level RNG.

```python
from dataclasses import dataclass, replace
import numpy as np
import simpy

@dataclass(frozen=True)
class Params:
    arrival_rate: float = 8.0      # per hour
    service_mean: float = 6.0      # minutes, lognormal
    service_sigma: float = 0.5
    n_servers: int = 2
    run_minutes: float = 8 * 60
    warmup_minutes: float = 60

@dataclass
class Results:
    waits: list[float]
    n_arrived: int = 0
    n_served: int = 0
    server_busy_minutes: float = 0.0

    def kpis(self, p: Params) -> dict[str, float]:
        w = np.asarray(self.waits)
        return {
            "mean_wait_min": float(w.mean()) if w.size else 0.0,
            "p95_wait_min": float(np.quantile(w, 0.95)) if w.size else 0.0,
            "utilization": self.server_busy_minutes
            / ((p.run_minutes - p.warmup_minutes) * p.n_servers),
            "throughput_per_hr": self.n_served / ((p.run_minutes - p.warmup_minutes) / 60),
        }

def run_one(p: Params, seed: int) -> Results:
    # One stream per source of randomness: adding a draw to one must not shift others.
    streams = {}
    for name, child in zip(
        ("arrival", "service"), np.random.SeedSequence(seed).spawn(2)
    ):
        streams[name] = np.random.default_rng(child)

    env = simpy.Environment()
    servers = simpy.Resource(env, capacity=p.n_servers)
    res = Results(waits=[])

    def customer(env):
        arrived = env.now
        with servers.request() as req:
            yield req
            wait = env.now - arrived
            duration = streams["service"].lognormal(
                np.log(p.service_mean) - p.service_sigma ** 2 / 2, p.service_sigma
            )
            yield env.timeout(duration)
        # Warm-up truncation happens here, at collection time -- not by starting the
        # run mid-stream, which would need a non-empty initial state to be meaningful.
        if arrived >= p.warmup_minutes:
            res.waits.append(wait)
            res.n_served += 1
            res.server_busy_minutes += duration

    def source(env):
        while True:
            yield env.timeout(streams["arrival"].exponential(60.0 / p.arrival_rate))
            res.n_arrived += 1
            env.process(customer(env))

    env.process(source(env))
    env.run(until=p.run_minutes)
    return res
```

Scenarios are then `replace(base_params, n_servers=3)` — a frozen dataclass makes a
scenario a one-line diff and keeps the baseline immutable.

## simpy primitives

| Need | Use |
|---|---|
| Servers, machines, staff (capacity N, FIFO) | `simpy.Resource` |
| Priority or preemption | `simpy.PriorityResource`, `simpy.PreemptiveResource` |
| Bulk stock: inventory, fuel, buffer level | `simpy.Container` |
| Discrete distinguishable items in a buffer | `simpy.Store`, `FilterStore` |
| Balking / reneging (customer gives up) | `yield req | env.timeout(patience)` |
| Shift patterns, breakdowns | A separate process that seizes all capacity |
| Batching | `Store` plus a process that waits for N items or a timeout |

Non-FIFO queue disciplines matter more than they look: switching FIFO to
shortest-job-first can cut mean wait substantially while making the tail worse, so
check which the State 1 KPI actually is.

## Verification (State 5)

DES code fails silently — a mis-scoped `with` block returns a resource too early and
the model simply reports lower utilization. So verify against cases with known answers.

**Analytic checks.** With exponential inter-arrivals and exponential service, the model
must reproduce M/M/1 or M/M/c. For M/M/1 with ρ = λ/μ < 1:

- L = ρ/(1−ρ) in system, Lq = ρ²/(1−ρ) in queue
- W = 1/(μ−λ) in system, Wq = ρ/(μ−λ) waiting
- utilization = ρ

Set the model to exponential service, run it long, and confirm it lands inside the
confidence interval of the analytic value. This single test catches most logic errors.

**Little's Law** holds for any stable system: L = λW. Compute both sides from
independently collected statistics; a mismatch means the collection is wrong even if
the mechanics are right.

**Conservation.** `n_arrived == n_served + n_in_system + n_balked` at the end of every
run. Assert it.

**Extreme conditions.**

| Condition | Expected |
|---|---|
| Zero arrival rate | Empty system, zero utilization, no waits |
| Service time → 0 | Zero wait, utilization → 0, throughput = arrival rate |
| Capacity → ∞ | Wait → 0, utilization → 0 |
| Capacity 1, ρ > 1 | Queue grows without bound — confirms instability is visible |
| Single entity | Wait exactly 0, service exactly its drawn duration |

**Tracing.** Log every event (time, entity, action, queue length) for a short run with a
fixed seed and read the first 50 lines by hand against the State 2 spec. Nothing else
finds an off-by-one in the routing logic as fast.

## Common DES mistakes

- **Releasing the resource too early.** Put the service `timeout` *inside* the `with`
  block. Outside it, servers are freed while still working and utilization is wrong.
- **Measuring wait from the wrong instant.** Wait in queue is request-to-seize; time in
  system is arrival-to-departure. State 1 named one of them.
- **Running an unstable system and reporting a mean.** If ρ ≥ 1 the queue diverges and
  the "mean wait" is just a function of run length. Check ρ before interpreting.
- **Time units drifting.** Rate per hour, service in minutes, run length in days — pick
  one unit, put it in the parameter names, and convert at the boundary only.
- **Warm-up by discarding the first N entities instead of the first N time units.** Those
  differ whenever the arrival rate varies.
- **Collecting statistics for entities still in the system at run end.** They bias
  results downward; either exclude them or note the censoring.
