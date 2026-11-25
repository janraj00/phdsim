# One decision, two information needs

Implemented as an isolated analytical calculator on 2026-11-15, after the user
asked to start building the minimal mechanism. This is the active two-question
example; the earlier [single-question walkthrough](SCOUT_SINGLE_FORK_SCENARIO.md)
is historical. No mission-controller or shared message-contract behavior was
changed. This calculator does not execute a world, train a model, or integrate
Jev/A2A.

For the subsequent automatically generated viewpoints and a path-based
information baseline, see [automatic needs and poses](SCOUT_PATH_AWARE.md).
That matched comparison uses perfect reports, separately from this noisy fixture.

## Run

From the SCOUT worktree, using Python 3.11+:

```sh
PYTHONPATH=src python3 -m phdsim.experiments.scout.single_decision

PYTHONPATH=src python3 -m phdsim.experiments.scout.single_decision \
  --config configs/scout/single_decision.json \
  --output runs/<fresh-directory>
```

The verified desktop executable is
`/Users/janek/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`
(Python 3.12). Use it instead of the older system `python3` if necessary.
Output directories are created exclusively and never overwritten.

The report shows the public grid, conditional route costs and ranked observation
proposals. `input.json` preserves the configuration. `estimates.json` includes
per-report probabilities, posterior beliefs, selected routes and input/source
hashes. These are model predictions, not realized mission outcomes or labels.

## Public geometry and continuation model

The 15 by 15 public corridor map has rover start `(1, 7)`, fork `(5, 7)` and
goal `(13, 7)`. One uncertain passage lies on each branch. All other corridor
cells are known free; cells outside the corridors are known rover obstacles.
The drone may fly over those obstacles in the simplified flight model.

| Branch | Waypoints | Question | P(blocked) | Open length |
|---|---|---|---:|---:|
| Upper | fork, `(5,4)`, `(13,4)`, goal | `(9,4)` | 0.5 | 14 |
| Lower | fork, `(5,11)`, `(13,11)`, goal | `(9,11)` | 0.3 | 16 |

The rover takes four ticks along the common approach, so the result deadline
is tick 4. A result available exactly then is processed before route selection.
Neither question enters the rover's radius-2 footprint on this approach.
Thus the default has no new diagnostic own measurement before the fork; the
rover's knowledge is not being frozen by the estimator.

After the fork, the continuation model follows the selected route. On a blocked
entry, it spends one tick, returns to the fork and tries the other route. There
is no further drone request or voluntary early route switch in this model.
This is a fixed continuation assumption, not the existing mission planner's
full replanning behavior. The one optimized route choice occurs at the fork.

The upper passage is reached after six successful steps, the lower after seven.
Consequently, choosing the blocked branch and then succeeding on the other
costs `6+1+6+16 = 29` or `7+1+7+14 = 29`. If both branches are blocked, either
choice gets the same failure penalty, `time_budget + 1 = 61`:

| Upper/lower state | Choose upper | Choose lower |
|---|---:|---:|
| Free/free | 14 | 16 |
| Free/blocked | 14 | 29 |
| Blocked/free | 29 | 16 |
| Blocked/blocked | 61 | 61 |

The costs come from public geometry and the declared continuation, not knowledge
of which state is true. The objective minimizes expected route time-cost,
including the fixed failure penalty, under an incremental acquisition energy
limit of 6. The common approach cost is identical for all actions and omitted
from the comparison. Equal costs prefer lower energy, then no query.

## Observation proposals and quality boundary

The drone starts at `(2,3)`, has speed 3 and sensing duration 1. Flight timing,
footprint and incremental flight/sensing/response energy reuse the existing
helper quote and accounting code. Transmission adds zero time.

Three representative poses are supplied as public quote fixtures: upper passage,
lower passage and a joint view from `(9,7)`. This is a bounded candidate set,
not an exhaustive viewpoint generator or an optimized multi-stop drone route.

The approved sensor likelihoods are explicitly supplied in the fixture:
accuracy 0.90 at distance 0, 0.72 at distance 3 and 0.66 at distance 4; no
coverage beyond radius 5. No second distance-quality implementation is added.
The fixture is checked at these specific distances, and coverage is checked
against the existing footprint implementation. The legacy constant-accuracy
`observe()` is never called by this calculator.

Before integration into sensing/movement, reconcile the approved sensor owner's
source with the current legacy snapshot. New positions need corresponding
owner-supplied likelihoods; do not reuse these fixture numbers indiscriminately.

## Exact pre-measurement calculation

`decision/acquisition/recipient_value.py` receives immutable local decision
context and observation quotes. It supports one or two independent binary
questions and exactly two recipient route choices. It enumerates belief
hypotheses and possible reports, performs Bayesian updates, chooses the lowest
expected route cost **after each possible report**, and averages over reports.
There is no hidden-world access, observation sampling or simulator forking.

Different questions and sensor errors are assumed independent conditional on
the question states. These assumptions are explicit and are not general claims
about real terrain or sensors. Unknown likelihoods are not assigned zero value:
every covered question needs an explicit valid likelihood. `None` means no
coverage. An energy-infeasible quote has no estimated accepted-action value.

The no-query comparison retains any explicitly shared forecast own observations
before the same deadline. The small calculator can receive up to two such
forecasts; they contain timing and likelihoods, not future measurement values.
This is an internal analytical input, not an implemented extension to the wire
contracts. Forecasts after the decision are ignored for this decision.

Inspected default output:

| Option | Result tick | Expected route cost | Expected saving |
|---|---:|---:|---:|
| Observe upper | 4 | 22.50 | 2.20 |
| Observe both | 4 | 23.85 | 0.85 |
| No new observation | — | 24.70 | 0 |
| Observe lower | 5 | 24.70 | 0; too late |

The selected quote observes the upper passage. These values are conditional on
the declared belief, cost, sensing and timing model. They establish the
calculator's example behavior, not expected physical mission gains or a new
method's superiority. The original 104 hindsight labels are separate data.

## Verification and remaining integration

```sh
PYTHONPATH=src python3 -m unittest \
  tests.test_scout tests.test_scout_counterfactual tests.test_scout_recipient_value -v
```

32 tests passed in this source snapshot: 18 existing checks and 14 new checks.
New checks include an independently hand-computed one-question example; noisy
versus perfect evidence; exact-deadline and late results; energy limits; zero
incremental value; future own evidence in the baseline; changes in recipient
consequences changing which question is observed; joint coverage; geometry-based
costs; explicit quote quality; provenance and output preservation.

Remaining work is to connect proposal generation to the authoritative sensor,
then connect need/offer/acceptance/result exchange to the mission clock and
agent containers. Shared contract changes belong to coordinated integration.
The existing mission loop, policy factory, sensor and CLI are unchanged.
