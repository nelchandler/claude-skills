# claude-skills

[Claude Code](https://claude.com/claude-code) skills, packaged as an installable plugin
marketplace so they work in every project rather than one repo.

## Install

```bash
/plugin marketplace add nelchandler/claude-skills
/plugin install simulation-engineer@skills
```

Or non-interactively:

```bash
claude plugin marketplace add nelchandler/claude-skills
claude plugin install simulation-engineer@skills
```

Update later with `/plugin marketplace update skills`.

## Skills

### simulation-engineer

An Operations Research and simulation engineering agent. It runs the standard 8-step
simulation lifecycle as an explicit state machine — problem formulation, conceptual
modeling, input modeling, translation, verification, validation, experimental design,
execution and analysis — and does not skip steps.

The reason for the gating: simulation output is plausible by construction. A model with an
invented arrival distribution and no warm-up analysis still prints a tidy mean queue length
to three decimals, and a stakeholder cannot tell that number from a real one. Each step has
a gate that must clear before the next begins.

Covers discrete-event (`simpy`), agent-based (`mesa`), system dynamics, static Monte Carlo,
and Markov/regime-switching models, with reference material per paradigm:

| Reference | Contents |
|---|---|
| `input-modeling.md` | Distribution fitting, K-S and chi-square caveats, three-point/PERT estimates, copulas for correlated inputs |
| `discrete-event.md` | simpy structure, queue disciplines, M/M/1 and Little's Law verification, common DES mistakes |
| `agent-based.md` | mesa scheduling regimes, mean-field checks, pattern-oriented validation |
| `markov-economic.md` | Closed forms before simulation, regime switching, exact vs Euler SDE schemes |
| `experiment-design.md` | Welch warm-up, replication sizing, common random numbers, batch means, ANOVA, rare events |

**Trigger it** by describing anything stochastic you want sized or compared — queues,
capacity, staffing, throughput, lead times, inventory, risk, load models, regime-switching
paths, what-if scenarios — or type `START` for the guided workflow from step 1.

#### Bundled tooling

`skills/simulation-engineer/scripts/simkit.py` is the statistics every simulation study
otherwise re-derives, with the parts that are easy to get subtly wrong done once:

- `seed_streams` — independent RNG streams via `SeedSequence.spawn`, not `seed + i`
- `mc_summary` / `bootstrap_ci` — Student-t and percentile-bootstrap intervals
- `n_for_halfwidth` — replications needed for a target precision, instead of guessing 1000
- `batch_means` — steady-state intervals from one long run, warning when batches stay correlated
- `welch_warmup` — warm-up truncation point from replication traces
- `crn_compare` — paired scenario comparison that reports its *achieved* variance reduction,
  so broken common-random-number alignment shows up as a number rather than a silent loss

Requires `numpy`. `scipy` is optional — quantiles fall back to Acklam and Cornish-Fisher
approximations when it is absent, so the module works in a bare environment. `simpy` and
`mesa` are only needed for those paradigms.

```bash
pip install numpy scipy          # scipy optional but recommended
pip install simpy mesa           # per paradigm, as needed
```

#### Tests

29 tests covering the statistics rather than merely execution — quantiles against published
values, interval coverage against its nominal rate, batch means against an AR(1) process with
known autocorrelation, stream independence under changed draw order, and common random
numbers where the variance reduction is analytically predictable.

```bash
cd plugins/simulation-engineer/skills/simulation-engineer/scripts
python -m pytest test_simkit.py -q
```

## Adding another skill

Drop it at `plugins/<name>/skills/<name>/SKILL.md` with a `.claude-plugin/plugin.json`
beside it, then add an entry to the `plugins` array in `.claude-plugin/marketplace.json`.
Installers pick it up on the next `/plugin marketplace update`.

## License

MIT — see [LICENSE](LICENSE).
