# SCOUT synthetic pilot v0

For logical ownership (rover, drone, environment, communication, simulation and
offline analysis), see [SCOUT components](SCOUT_COMPONENTS.md). The module map
below describes where reusable implementations live, not which agent owns them.

Implemented 2026-11-11 on branch `scout`, in a separate worktree. This is a
diagnostic experiment for acquisition mechanics, not a planetary simulator or
a new research method. Repository cleanup remains a separate later task.

## Run

Use **Python 3.11+**, with no third-party dependencies, from this worktree:

```sh
PYTHONPATH=src python3 -m phdsim.cli scout \
  --config configs/scout/pilot.json --compare --output runs/scout-first

PYTHONPATH=src python3 -m phdsim.cli scout \
  --config configs/scout/pilot.json --compare --seeds 42 43 44 45 46 \
  --output runs/scout-five-seeds

PYTHONPATH=src python3 -m unittest tests.test_scout -v
```

Choose a fresh output directory; existing runs are never overwritten. The
tested desktop executable is
`/Users/janek/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`
(Python 3.12). Substitute it for `python3` if the system executable is older.
No heavy PSTNet/UrbanIng installation is needed.

The executable config is JSON (`configs/scout/pilot.json`) to avoid adding a
YAML dependency. Its fields correspond to the discussed configuration:

| Field | Meaning |
|---|---|
| `world.generator` | Only `alternative_corridors`: a wall with two candidate passages, one closed. |
| `world.initial_map` | Only `uncertain`: coarse wall layout, P(blocked)=0.5 at passages, low occupancy prior elsewhere; the open passage is hidden. |
| `seed` | Reproduces the world, measurements and link delays; compared policies use paired world seeds. |
| `agents` | Speed, sensor radius/accuracy and movement energy coefficients. |
| `communication.delivery_delay` | Inclusive min/max positive integer ticks after capture. Actual delay is hidden from the policy until delivery. |
| `mission` | Joint time and energy budgets in synthetic units, not Mars-calibrated quantities. |
| `planning` | Dijkstra cost `1 + risk_weight * P(blocked)` and a hard probability threshold. This is a heuristic, not a formal chance constraint. |
| `acquisition` | Route lookahead, mean entropy threshold in bits, request cap and cooldown. |
| `policy` | `no_scouting` or `uncertainty_scouting`; use `--compare` for both, `--policy` for one. |

The illustrative entropy threshold of0.35 bits exercises requests with this
prior. It is not a validated parameter or a mission-value estimate.

## Information and execution

`environments/` holds hidden truth; `sensors/` generates noisy binary observations.
`belief/` fuses delivered measurements using Bayes' rule; successful entry and blocked movement attempts supply
reliable contact evidence. Start and goal are known free. `planning/` uses
only the rover belief. `decision/acquisition/` receives an immutable `DecisionView` with
that belief, pose/goal, known resources, busy status, request history and the
last received helper position. It has no truth, evaluator scores or future
payloads. Helper position is updated in this view only on response delivery.

Each tick processes captures/deliveries and rover arrivals before new decisions.
When ready, the rover senses locally, replans, optionally requests a view, and
attempts a step. The helper checks feasibility. An accepted request schedules
flight completion plus measurement time; the measurement is generated there,
then delivered after a sampled link delay. Only delivery updates rover belief.
There is at most one active helper request. The rover continues during flight.

World, sensor and link randomness use separate deterministic keys. Sensor noise
depends on sensor, tick and cell, so drone random draws cannot shift the rover
random stream. Measurements at different ticks are independent by assumption;
real temporally correlated sensor errors are not modeled here.

Truth and delivered cell values are available to offline reporting only. These
files must not be supplied to a deployed acquisition policy.

## Accounting and limitations

- A successful or blocked rover step costs the configured movement charge.
  Blocked entry is prevented and logged, not treated as a quantified physical
  safety event.
- Full flight, sensing and response energy is reserved at request acceptance,
  including work pending at termination. `energy_reserved` is conservative
  reservation accounting, not measured consumption. Components are reported.
- Bytes count only delivered cell records. Request/ACK overhead is omitted;
  acceptance is immediate. Pose metadata arrives with the response.
- Rover sensing, waiting and computation currently cost no energy. There is
  no return flight, altitude dynamics, charging or communication routing.
- Drone distance is Euclidean. Rover motion is one cell per `ceil(1/speed)`
  ticks, at least one tick; rover speed above1 does not improve throughput.
- The only automatic waiting occurs when no believed route exists and a
  response is pending. Explicit wait/slow policies are future work.
- Goal or failure terminates the run without draining the queue. Captures,
  deliveries and pending requests are reported separately.

## Outputs and checks

Each run has JSON results and JSONL events. The seed SVG compares offline truth,
initial belief and final belief with route and request targets. `summary.json`
contains per-mission outcomes and descriptive aggregates; durations include
failed missions. Resolved configs, input-config hash, code fingerprint and Git
HEAD record provenance even before committing. Generated outputs are ignored.

The inspected five-seed diagnostic (42–46) completed all ten missions. Ticks
were35/35,35/35,31/31,64/63,33/33 for no-scouting/scouting; scouting used2–3
requests and more reserved energy. This verifies execution, not superiority.

Ten tests cover feasible/reproducible worlds, Bayesian fusion, contact facts,
early-delivery exclusion, stale helper metadata, capture/delivery ordering,
energy rejection, paired runs, config validation, output preservation and the policy/belief import boundary.

## Next step

Offline single-action comparisons are now implemented; see
[counterfactual labels](SCOUT_LABELS.md). They preserve pending requests and
separate local inputs from hindsight scores. These are not yet a deployable
belief-sampled online value planner. Extend the map families and collect
independent world groups before fitting a fast surrogate; explicit waiting and
federation remain later extensions.


## Module map after the responsibility-based refactor

| Module | Responsibility | Main files |
|---|---|---|
| `environments/` | Hidden physical map and seeded map generation; no acquisition decisions. | `grid.py`, `corridors.py` |
| `sensors/` | Observation contract, field of view and noisy binary measurement generation at capture time. | `observations.py`, `occupancy.py` |
| `belief/` | Rover knowledge: Bayesian fusion of received observations, reliable contact facts and entropy. | `occupancy.py` |
| `planning/` | Choose a route from the local belief and navigation costs. | `grid.py` |
| `decision/acquisition/` | Choose whether/where to request information from an immutable local view; each strategy is separate. | `view.py`, `no_scouting.py`, `uncertainty.py`, `factory.py` |
| `agents/` | Rover movement state and drone flight quotation/feasibility. Controllers cannot inspect hidden terrain. | `rover.py`, `drone.py` |
| `communication/` | Response payload size and sampled transmission delay. | `delayed.py` |
| `costs/mission.py` | Joint energy ledger, with rover charges and drone reservations. | `mission.py` |
| `simulation/` | Scenario validation, event clock and mission execution; this layer may access truth to simulate physics. | `config.py`, `events.py`, `mission.py` |
| `evaluation/mission.py` | Offline metrics and truth/belief snapshots after the mission. | `mission.py` |
| `experiments/scout/` | JSON config loading, component composition, paired runs, provenance and SVG/JSON reports. | `config.py`, `mission.py`, `runner.py`, `provenance.py`, `report.py` |
| `cli/scout.py` | Parse arguments and dispatch the experiment. | `scout.py` |
| `core/` | Shared cell coordinates and deterministic random streams. | `grid.py`, `randomness.py` |

Configuration classes live beside their owners (e.g. `DroneConfig` in
`agents/drone.py`). `simulation/config.py` composes and validates them into a
scenario; `experiments/scout/config.py` only reads JSON. Domain modules do not
import the experiment package. `phdsim.scout` contains only the old command
alias; no simulation implementation remains there.

Data flow:

```text
environment --capture via sensor--> observation --delivery via link--> belief
                                                                      |
                                                   route planner <----+
                                                                      |
                                      acquisition policy <--- local decision view
                                                   |
                                       drone feasibility + energy reservation
                                                   |
                                       timed flight / capture / delivery
```

`simulation/mission.py` coordinates this loop. Selecting an observation does
not itself fuse it, and capturing it does not make it available to the rover.
Offline evaluation and reporting run after mission execution.

The module refactor was checked against complete pre-refactor outputs for
seeds42–46 and both policies: summaries, every event, trajectories and final
beliefs were identical. The configuration format and old
`python -m phdsim.scout` command are retained. The source fingerprint now lists
and hashes files across all participating packages, not just the old folder.
