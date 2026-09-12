# Markov, regime-switching, and Bayesian economic models (State 4)

Use these when the system has a small discrete state space, or when the quantity of
interest is a path of an economic variable whose dynamics change with an unobserved
regime. The distinguishing advantage over DES and ABM: much of the analysis is exact,
so simulation becomes a check rather than the only tool.

## Solve before you simulate

For a finite Markov chain, the things people usually simulate to estimate are available
in closed form. Simulating them adds Monte Carlo noise to an exact answer.

```python
import numpy as np

def stationary(P: np.ndarray) -> np.ndarray:
    """Stationary distribution of a row-stochastic matrix, from the dominant eigenvector."""
    assert np.allclose(P.sum(axis=1), 1.0), "rows must sum to 1"
    vals, vecs = np.linalg.eig(P.T)
    pi = np.real(vecs[:, np.argmin(np.abs(vals - 1.0))])
    return pi / pi.sum()

def expected_hitting_times(P: np.ndarray, target: int) -> np.ndarray:
    """E[steps to reach target] from each state: solve (I - Q) h = 1 on transient states."""
    n = P.shape[0]
    keep = [i for i in range(n) if i != target]
    Q = P[np.ix_(keep, keep)]
    h = np.linalg.solve(np.eye(len(keep)) - Q, np.ones(len(keep)))
    out = np.zeros(n)
    out[keep] = h
    return out
```

Also exact and worth reaching for before simulating: the n-step distribution
(`pi0 @ np.linalg.matrix_power(P, n)`), absorption probabilities, expected time in each
state before absorption, and — for a CTMC with generator `Q` — the transient
distribution via `scipy.linalg.expm(Q * t)`.

Simulate when the state space is too large to enumerate, the dynamics are path-dependent
in a way the chain cannot express, the payoff is a nonlinear function of the whole path
(a drawdown, a barrier, an option), or you need the *distribution* of an outcome rather
than its expectation.

## Regime-switching models

The standard form: a latent state `s_t` follows a Markov chain with transition matrix
P, and the observable follows regime-dependent dynamics.

```python
def simulate_regime_switching(P, mus, sigmas, n_steps, rng, s0=0):
    """Markov regime-switching returns. mus/sigmas are per-regime parameters."""
    P = np.asarray(P, dtype=float)
    assert np.allclose(P.sum(axis=1), 1.0)
    states = np.empty(n_steps, dtype=int)
    returns = np.empty(n_steps)
    s = s0
    for t in range(n_steps):
        s = rng.choice(len(P), p=P[s])
        states[t] = s
        returns[t] = rng.normal(mus[s], sigmas[s])
    return states, returns
```

Modeling notes that matter more than the code:

- **Persistence is the parameter that drives everything.** Expected regime duration is
  `1 / (1 - P[i, i])`. A crisis regime with `P[1,1] = 0.95` lasts ~20 periods on average;
  at 0.8 it lasts 5. Sanity-check these durations against history before running anything
  — an implied duration of 1.5 months for a recession means the matrix is wrong.
- **Regimes must be economically identified**, not just statistically fitted. Two-regime
  fits on any noisy series will happily find "high-vol" and "low-vol" states that mean
  nothing. Name what each regime is and check its estimated parameters against that story.
- Fit with the Hamilton filter / EM, or use `statsmodels.tsa.regime_switching.
  markov_regression` / `MarkovAutoregression`. Report the smoothed regime probabilities
  against known historical episodes as the validation step (State 6).
- Regime-switching models capture fat tails and volatility clustering that a single
  normal cannot. That is usually the reason to reach for one, so verify the simulated
  output actually exhibits them — kurtosis, and the autocorrelation of squared returns.

## Continuous paths: discretization is a real error source

For a continuous-time process, a naive Euler step introduces bias that does *not* shrink
with more replications — only with a smaller step. Where an exact scheme exists, use it.

Geometric Brownian motion has one:

```python
# Exact: log S is Brownian with drift. No discretization error at any dt.
log_increments = (mu - 0.5 * sigma ** 2) * dt + sigma * np.sqrt(dt) * rng.normal(size=(n_paths, n_steps))
paths = s0 * np.exp(np.cumsum(log_increments, axis=1))
```

Euler on `dS = mu S dt + sigma S dW` gives the same answer only as `dt -> 0`, and can
produce negative prices at large steps. Ornstein-Uhlenbeck and CIR also have exact or
near-exact schemes. When only Euler is available (a general SDE), demonstrate
convergence: halve `dt` and show the KPI stabilizes, and report the step used.

## Verification (State 5)

- Rows of every transition matrix sum to 1; all entries in [0, 1]. Assert on
  construction, since a matrix normalized by column instead of row silently produces a
  plausible but wrong chain.
- Long-run simulated state frequencies converge to `stationary(P)`. This is the single
  best check on a chain simulator.
- Simulated mean hitting times match `expected_hitting_times(P, target)` within their
  confidence interval.
- Degenerate cases: `P = I` freezes the state; a single regime reduces to the
  unconditional model and must reproduce its analytic moments.
- For a martingale (zero-drift GBM, a fair game), the simulated mean must be flat within
  its interval — a drift appearing from nowhere is the Itô correction handled wrongly.

## Economic and financial specifics

- **Report the distribution, not the expectation.** The expected outcome of a
  regime-switching path is rarely the decision-relevant quantity; VaR, expected
  shortfall, probability of breaching a covenant, and maximum drawdown are.
- **Tail statistics need far more paths than means.** Use `rare_event_n` in
  `scripts/simkit.py` to size the run before committing, and bootstrap the interval on a
  quantile rather than assuming a t interval applies to it.
- **Discounting and compounding conventions** are a frequent silent error. State whether
  rates are annualized, whether returns are log or simple, and convert once.
- **Calibrating to one historical period** produces a model of that period. Hold out a
  period, or at minimum report how the recommendation changes under parameters fitted to
  a different window.
