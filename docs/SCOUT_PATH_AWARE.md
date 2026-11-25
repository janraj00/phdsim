# Automatically choosing an information need and observation pose

Implemented on 2026-11-18 as an isolated analytical comparison. This extends
the [single-decision calculator](SCOUT_SINGLE_DECISION.md) with automatically
generated viewpoints and a route-based information heuristic. It does not
change the mission loop or shared cooperation contracts.

## Method and assumptions

The baseline is inspired by [Traversing Mars, section V-A, equation 7](https://arxiv.org/html/2406.05313v2#S5.SS1):
reward observation of unobserved cells on the follower's current optimistic
path. This implementation is a one-view adaptation, not a reproduction of the
paper's sampled trajectory tree, accumulated travel-cost score, exploration
modes, stopping rules or guarantees.

`decision/acquisition/path_aware.py` receives an immutable local probability
grid, observed mask, rover start/goal, drone position and public resource limits.
It has no physical world, future observation or simulation checkpoint.

1. Keep known obstacles blocked; temporarily treat unobserved cells as free.
2. Compute a shortest four-connected rover path using the existing planner.
3. Select unobserved cells on that path as information needs.
4. Enumerate every grid cell as a potential drone observation pose.
5. Quote flight, sensing, response energy and footprint using existing helpers.
6. Reject poses exceeding the energy limit or useful-until time. Otherwise score
   them by covered unknown path cells divided by flight-plus-sensing ticks.
7. Choose the highest score, with lower energy breaking ties; choose no query
   when no feasible pose covers an unknown path cell.

The observation target and measurement pose are separate. Drone flight may pass
above rover obstacles. Transmission delay is zero; flight and sensing consume
time. A report available exactly at the decision tick is usable.

For a controlled first comparison, both selectors receive **perfect binary
reports** within radius 5. Known cells are therefore exact, rather than noisy
beliefs. The approved distance-dependent sensor is not implemented again or
replaced. The previous three manual poses and likelihood fixtures are ignored.
These idealized numbers cannot be compared directly with the earlier noisy
three-pose result.

The second selector evaluates the same generated poses with the existing
expected-recipient-value calculator. Its objective minimizes expected route
time-cost under an acquisition energy limit, including the same fixed failure
penalty and backtrack continuation. Acquisition energy is a constraint and
tie-breaker, rather than a time-cost term. Both methods compare against no query.

## Two inspected cases

Both cases use the same public 15x15 corridor layout, route costs and priors
from `single_decision.json`. Each enumerates 225 poses; 137 cover at least one
unknown. The baseline automatically identifies upper passage `(9,4)` from its
optimistic path. The geometry, uncertainty locations/priors, start, goal and
fork deadline remain configured scenario inputs. This is not yet discovery of
forks on arbitrary maps.

| Case | Selector | Chosen pose | Result tick | Expected route cost |
|---|---|---|---:|---:|
| Four ticks before fork | No query | — | — | 24.70 |
| Four ticks before fork | Path coverage per tick | `(4,4)` | 2 | 21.75 |
| Four ticks before fork | Expected recipient gain | `(4,4)` | 2 | 21.75 |
| One tick before fork | No query | — | — | 24.70 |
| One tick before fork | Path coverage per tick | — | — | 24.70 |
| One tick before fork | Expected recipient gain | `(9,11)` | 1 | 22.45 |

In the first case the two methods agree. Pose `(4,4)` was not one of the previous
three manual candidates. Perfect upper information costs, in expectation,
`0.5*14 + 0.5*(0.7*16 + 0.3*61) = 21.75`.

The deliberately constructed second case moves the rover one step before the
fork and places the drone at the lower passage. It cannot observe the upper
passage before the decision. The path heuristic declines because the only
timely information is off its current optimistic path. Yet knowing the lower
passage changes the route decision: if free, choose lower at cost 16; if
blocked, choose upper at expected cost `0.5*14 + 0.5*61 = 37.5`.
Thus `0.7*16 + 0.3*37.5 = 22.45`, saving 2.25 against no query.

This diagnoses the scope of this particular one-view heuristic. It is not a
published benchmark or evidence against the original paper. Neither case
samples a measurement outcome or establishes a realized mission improvement.
Coverage measures relevance to one path; expected decision value measures the
consequences of all possible reports across the two route alternatives.

## Reproduce and inspect

Use Python 3.11+ from the SCOUT worktree, with a fresh output directory:

```sh
PYTHONPATH=src python3 -m phdsim.experiments.scout.path_aware_demo \
  --output runs/<fresh-base-case>

PYTHONPATH=src python3 -m phdsim.experiments.scout.path_aware_demo \
  --config configs/scout/path_aware_near_fork.json \
  --output runs/<fresh-near-fork-case>

PYTHONPATH=src python3 -m unittest tests.test_scout \
  tests.test_scout_counterfactual tests.test_scout_recipient_value \
  tests.test_scout_path_aware -q
```

Verified outputs: `runs/scout-path-aware-v0` and
`runs/scout-path-aware-near-fork-v0`. Each contains a map/report, a 225-row pose
table, original input and effective model inputs plus source/config hashes.
Ignored manual pose/quality fields are explicitly listed in `comparison.json`.
45 focused tests passed, including 13 new checks for automatic needs/poses,
belief updates, deadlines, resources, the off-path counterexample and provenance.

The next integration step is to obtain authoritative distance-dependent
likelihoods for generated poses, then retain decision-value ranking over needs
on multiple candidate routes. Online messages, rover self-observation forecasts,
context invalidation and repeated replanning remain integration work.
