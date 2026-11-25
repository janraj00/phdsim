# SCOUT elevation mapping benchmark

This experiment measures whether updating a good initial measurement schedule
with new information helps two drones and a rover reach a map quality target.
Both strategies begin with the same schedule and use the same scoring rule,
map representation, sensors, mobility, budgets and stopping rule.

## Run

```sh
PYTHONPATH=src python3 -m phdsim.cli scout-elevation \
  --config configs/scout/elevation.json --seeds 42 43 44 45 46 47 48 49 50 51 \
  --output runs/scout-elevation-demo
```

Use Python 3.11+ and a fresh output directory. The benchmark uses the standard
library. The output includes a coverage plot, a report with config and source
identity, and per-run event traces and final elevation estimates. The plot
shows offline accuracy and keeps the final map unchanged after a run ends.

## Scenario and comparison

The world has 32 × 32 one-metre cells grouped into 4 × 4 observation tiles.
The coarse initial model describes a broad slope and undulations. A spatially
smooth, hidden height residual creates local hills and depressions. Drones
choose a close view of one tile or a higher view of two by two tiles. A rover
takes close measurements on one tile. Ground and aerial measurement errors
depend on standoff to the tile centre. Travel takes simulated time and energy.
The robots can work concurrently, with at most one commitment per robot.

The simulator assigns each tile a persistent aerial imaging regime. Its local
value starts unknown. Aerial measurements report their realised noise variance
and reveal this regime for the observed tiles. The setting models an idealised
image quality diagnostic. Aerial and ground sensors both observe elevation.
The ground sensor is unaffected by the aerial imaging regime. Within a reading,
the simulated measurement noises of individual height samples are independent.

The planner chooses assignments from feasible sensor poses with a greedy search.
It scores the expected number of additional tiles that meet the quality
requirement per unit of action time. If no candidate crosses the quality
threshold, the score favours improvement toward the threshold. Both schedulers
account for active commitments as projected measurements. The fixed strategy
forecasts the full schedule before launch. The adaptive one executes the same
first assignments and reschedules free robots after measurements arrive. It
uses reported quality and preserves commitments already underway. Greedy
planning gives a shared, reproducible schedule and does not establish global
optimality.

A tile qualifies when its estimated probability of an elevation error within
25 cm is at least 90%. The mission declares completion when at least 85% of
the surface qualifies. Offline evaluation separately counts cells whose actual
absolute error is at most 25 cm. Success requires both a declaration and an
actual fraction of at least 85% at that time. The maps use Gaussian per-cell
updates with common precision within a tile. They do not model spatial
covariance, so the tile and map rules should be interpreted as pointwise
confidence criteria, not joint confidence in the whole region.

This simulation assumes exact poses, a common coordinate frame, a static
terrain and immediate sharing on a common map. Travel follows straight-line
kinematics and capture duration is a mode constant. Modelled energy is
reserved on dispatch, including unfinished work at termination. There is no
radio or byte budget in this comparison. These assumptions isolate planning
adaptation and leave explicit communication and detailed physics to later
experiments.

## Pilot results

| Paired worlds | Fixed plan verified | Adaptive plan verified | Mean actual surface within 25 cm, fixed / adaptive |
|---|---:|---:|---:|
| Seeds 42–51 | 0 / 10 | 3 / 10 | 85.86% / 86.91% |
| Repeat on seeds 100–139 | 2 / 40 | 6 / 40 | 85.08% / 85.64% |

Across the repeat, 19 fixed and 24 adaptive maps met the actual elevation
target at the end. Fewer trials could declare this from their estimated map
quality. No declaration was premature in these samples. The scripts retain
all runs and report elapsed time with unverified trials charged the full
time budget as a separate descriptive metric. The differences describe this
fixture and a first adaptive heuristic. They do not establish improvement
over other adaptive methods or on physical terrain.

Checks cover identical dispatch and traces when imaging quality is fully
known, identical initial commitments otherwise, feasibility of each robot's
schedule and independence of runtime decisions from offline truth evaluation.

## Completion rules on identical measurement traces

For each planner, the simulator records one trace until its resources or
useful actions run out. All completion rules are evaluated at the same
checkpoints, before the next dispatch. Each rule is scored at the **first**
checkpoint where it would declare success. Later observations cannot rescue
an early declaration. Acquisition and its scoring rule are identical across
the completion rules for a given trace.

- **Pointwise coverage.** At least 85% of cells must individually have an
  estimated probability of at least 90% of being within 25 cm.
- **Expected coverage.** Average the probabilities of being within 25 cm over
  all cells and declare at 85%. An average is an estimate of the area within
  tolerance. It does not give the probability of meeting the area requirement.
- **Calibrated coverage.** For each calibration mission, record the largest
  expected coverage observed while true coverage was below 85%. Compute the
  order statistic at rank `ceil((n + 1) * 0.95)` separately for each planner.
  Declare completion when the score exceeds that threshold and reaches 85%.
  Using a maximum over the mission accounts for repeated opportunities to
  stop. Under exchangeability across full mission traces, the rank rule
  bounds premature declarations marginally over missions and calibration
  sets at the chosen 5% level. It does not bound the error rate among
  declarations or guarantee performance on shifted terrain. This uses the
  standard split conformal rank argument. [Lei et al., JASA](https://arxiv.org/abs/1604.04173).

The holdout uses 200 calibration worlds (seeds 1000–1199) and a separate
200 test worlds (seeds 2000–2199), each run with both planners. The calibrated
thresholds were 86.08% for the fixed plan and 86.25% for the adaptive plan.

| Planner | Completion rule | Verified declarations | Premature declarations |
|---|---|---:|---:|
| Fixed | Pointwise coverage | 10 / 200 | 0 / 200 |
| Fixed | Expected coverage | 75 / 200 | 39 / 200 |
| Fixed | Calibrated coverage | 65 / 200 | 8 / 200 |
| Adaptive | Pointwise coverage | 34 / 200 | 1 / 200 |
| Adaptive | Expected coverage | 95 / 200 | 44 / 200 |
| Adaptive | Calibrated coverage | 84 / 200 | 6 / 200 |

On the 32 adaptive traces both the pointwise and calibrated rules verified,
the calibrated rule stopped on average 4.53 ticks earlier. The test also
found that 141 adaptive traces reached 85% actual coverage at some point.
The calibrated rule missed some of these opportunities. Across the original
40 pairs, the pointwise rule reproduced all 80 trace prefixes and outcomes.
For those worlds the calibrated rule produced 7 verified and 5 premature
declarations for the fixed plan, and 15 verified and 1 premature for the
adaptive plan. Rates on one test set and for a single fitted threshold vary.

```sh
PYTHONPATH=src python3 -m phdsim.cli scout-elevation \
  --config configs/scout/elevation.json --calibration-seeds {1000..1199} \
  --seeds {2000..2199} --output runs/scout-elevation-stopping-replay
```

The stopping comparison writes `summary.json` with the calibration scores
and `test_traces.jsonl` with all test checkpoints. The default simulator still
uses the pointwise rule. Calibrated stopping here is evaluated on simulated
data drawn from the same scenario generator used for calibration.
