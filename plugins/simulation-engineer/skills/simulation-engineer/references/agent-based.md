# Agent-based modeling with mesa (States 4–5)

Use ABM when the mechanism under study *is* the interaction between heterogeneous
individuals, and the macro outcome is emergent rather than assumed. Segregation from
local preferences, adoption cascades through a network, herding in a market, congestion
from individual routing choices.

Ask first whether the interaction is load-bearing. If agents merely pass through a
sequence of resources without influencing each other, DES answers the same question with
a fraction of the code and a validated analytic check available. ABM buys expressiveness
at the cost of losing almost all closed-form verification, which makes State 5 harder —
spend that cost deliberately.

## Structure

```python
import mesa
import numpy as np
from dataclasses import dataclass

@dataclass(frozen=True)
class Params:
    n_agents: int = 500
    n_steps: int = 200
    adoption_threshold: float = 0.3   # fraction of neighbours needed to switch
    network_k: int = 6

class Adopter(mesa.Agent):
    def __init__(self, model, threshold: float):
        super().__init__(model)
        self.threshold = threshold
        self.adopted = False

    def step(self):
        if self.adopted:
            return
        neighbours = self.model.grid.get_neighbors(self.pos, include_center=False)
        if not neighbours:
            return
        share = sum(a.adopted for a in neighbours) / len(neighbours)
        # Stage the decision; apply it in advance() so the whole population
        # updates from the same state rather than from a half-updated one.
        self._next = share >= self.threshold

    def advance(self):
        self.adopted = getattr(self, "_next", self.adopted)

class AdoptionModel(mesa.Model):
    def __init__(self, p: Params, seed: int):
        super().__init__(seed=seed)          # mesa routes this to self.random
        self.p = p
        self.rng = np.random.default_rng(seed)   # keep numpy draws seeded too
        ...
        self.datacollector = mesa.DataCollector(
            model_reporters={"adopted_share": lambda m: np.mean(
                [a.adopted for a in m.agents])}
        )

def run_one(p: Params, seed: int) -> dict:
    model = AdoptionModel(p, seed)
    for _ in range(p.n_steps):
        model.step()
    return model.datacollector.get_model_vars_dataframe().to_dict("list")
```

Two seeding points, not one: `mesa.Model(seed=...)` seeds `self.random` (used by
agent shuffling and mesa's own draws), while any `numpy` sampling you do needs its own
generator. Seeding one and not the other produces runs that are only half reproducible,
which is worse than neither because the irreproducibility is intermittent.

## Scheduling — decide it, don't inherit it

Activation order is a modeling assumption with large effects, not an implementation
detail. Three regimes:

- **Simultaneous** (`step` stages, `advance` commits, via `AgentSet.do("step")` then
  `.do("advance")`): every agent decides from the same world state. Correct when the
  real decisions are concurrent.
- **Random activation** (`model.agents.shuffle_do("step")`): agents see partially
  updated state, in a different order each step. Correct when interactions really are
  sequential and order is arbitrary. Re-shuffle every step — a fixed order creates
  artefacts where early agents systematically dominate.
- **Staged**: multiple phases per step (all agents move, then all agents trade).

State which you chose and why in the State 2 spec. Then test sensitivity to it: if
switching random activation to simultaneous changes the conclusion, the conclusion is
about your scheduler, not the system.

## Verification without closed forms (State 5)

ABM has few analytic anchors, so lean on invariants and limits.

- **Conservation.** Total money, agents, or mass is constant unless a rule creates or
  destroys it. Assert every step, not only at the end.
- **Degenerate parameters with known answers.** Threshold 0 → everyone adopts in one
  step. Threshold above 1 → nobody ever adopts. Zero interaction radius → agents evolve
  independently and the population mean matches a single-agent calculation.
- **Single agent.** Run with `n_agents=1` and hand-check the trajectory.
- **Well-mixed limit.** With a complete graph and many agents, many ABMs converge to
  their mean-field ODE. Solve that ODE and compare — this is the closest thing to an
  analytic check available, and it is worth the effort when it applies.
- **Reproducibility test.** Same seed twice, identical output arrays. Set order
  iteration or a dict keyed by object identity will break this; that is the bug that
  makes months of results irreproducible.
- **Scale invariance.** Where the model has no intrinsic scale, results should be stable
  in n_agents. If the answer changes systematically from 500 to 5000 agents, either
  there is a finite-size effect worth understanding or a normalization bug.

## Validation (State 6)

Validate on the *pattern*, not the trajectory. A single realization of an ABM is not
expected to match history point-by-point; the model is credible if history looks like a
plausible draw from the model's ensemble. Practical form: run n replications, plot the
ensemble band of each KPI, and check that the historical path stays inside it. Then
check the qualitative signature — the shape of the adoption curve, the cluster-size
distribution, the presence of a phase transition — against the stylized facts the domain
literature reports. Pattern-oriented modeling calls this validating against multiple
patterns at once, and it is far more informative than matching one aggregate number.

## Experiment design notes specific to ABM

- ABM output is often **heavy-tailed or multimodal** — a cascade either takes off or
  fizzles. The mean of a bimodal outcome describes nothing. Report the probability of
  each regime plus the conditional means, and check a histogram of replication outcomes
  before reporting any mean at all.
- **Replications are needed for the same parameters**, not only across parameters.
  Stochastic ABMs with identical inputs land in qualitatively different places.
- **Parameter space is large.** Use Latin hypercube or Sobol sampling for sweeps rather
  than a full factorial grid, and report a sensitivity ranking so the reader knows which
  three of the twelve parameters actually drive the outcome.
- Interaction topology is a parameter. Run at least one alternative network structure;
  results that hold only on a lattice are results about lattices.
