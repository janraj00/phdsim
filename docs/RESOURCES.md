# Comparing quality, computation and resources

These are research-design notes, not an implemented physical energy model.
Acquisition is the main comparison target: when, from whom and which observation
to request. Hold perception and fusion fixed when isolating acquisition strategies.

## Measurements

Report quality alongside the resources required to achieve it. Parameter count
does not by itself measure energy use or guarantee better decisions. Record:

- Parameter count and checkpoint bytes.
- Peak runtime memory, including method state and buffers.
- Operations per decision and measured decision latency, including median and p95.
- Time, energy and frequency of model updates.
- Quality after a fixed number of interactions or training examples.
- Energy per decision and average power at a specified operating frequency.

A bandit's uncertainty matrices, optimizer state or replay buffer may require more
memory than its prediction weights. For example, 300 float32 coefficients occupy
1,200 bytes before accounting for any additional state.

## Experimental controls

Use the same task and information-access rules. Separate offline fitting from
runtime execution. Report offboard training separately; include in-flight updates
in onboard resource costs. Compare quality at shared memory, latency and energy
budgets, with repeated runs and uncertainty estimates. Use quality/cost Pareto
fronts rather than a single quality-per-parameter ratio.

The current implementation counts pulls and PNG bytes. A gated execution report
measures local preprocessing, inference and decisions; it excludes network
transport. Counterfactual-cache evaluation does not measure deployment latency.
CPU measurements are not directly comparable to the authors' AGX Xavier timings.

## Future physical simulation

Profile methods on specified hardware with `peak_memory_bytes`, `decision_time_s`,
`decision_energy_j`, `update_time_s`, `update_energy_j`, and decision/update rates.
A possible simulation energy step is:

```text
E_next = E_current
         - (P_flight + P_base + P_communication) * dt
         - n_decisions * e_decision
         - n_updates * e_update
```

Decision and update energy must be incremental to base power to avoid double
counting. Memory is first a feasibility constraint; do not assume a fixed energy
cost per parameter. Calibrate energy values on target hardware. Without measurements,
label assumptions and perform sensitivity analysis.

Include the effect of decision quality and delay on flight. Extra computation may
be offset by shorter routes or less hovering. Mission-level evaluation should
include success, total energy, duration and completed fleet tasks. Hardware, mass
or purchase-budget constraints must explain any reduction in fleet size. Fixed
fleet size and fixed fleet budget are distinct scenarios.

## Methodological references

- [LinUCB: linear prediction and uncertainty state](https://archives.iw3c2.org/www2010/_lihong/pub/Li10Contextual.pdf).
- [MLPerf: system- and workload-specific energy measurement](https://mlcommons.org/benchmarks/inference-datacenter/).
- [MAVBench: computation, flight and mission energy](https://arxiv.org/html/1905.06388v2).
