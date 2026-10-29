# UrbanIng joint subset acquisition

Status, 2026-10-29: **implemented and tested**, including replay of all 20 saved
real frames. **No gain model has been trained or evaluated on real held-out
recordings.** The existing two windows belong to the same recording and cannot
serve as independent policy training/validation sets.

## Decision and permitted evidence

Car1 chooses among no acquisition, Car2, Infra and both. Only feasible distinct
subsets are candidates; an unavailable partner is not counted as a request and
fallback aliases are not sampled twice. Infra remains a bundled LiDAR site.
This is one decision before acquiring partner payloads, not sequential replanning.

The ridge predictor has three independently fitted output heads: the expected
gain of Car2, Infra, and **their joint subset**, all relative to Car1. The joint
gain is learned directly, not assumed to equal the sum of the individual gains.
It is compared with zero for no acquisition. Selection maximizes predicted gain
minus a predeclared nonnegative penalty per requested bundle; ties prefer fewer
requests and then the fixed action order.

Inputs are Car1's entropy, postprocessed detection count and score summaries
(overall and per class), plus which source categories are available. There are
16 features. Frame IDs/timestamps are excluded from learned features. Geometry,
peer confidences and peer observations are not used. Source availability is
assumed to be known metadata, as in stage 1.

Offline targets use the change in **frame micro F1 at BEV IoU 0.5**. Predictions
are matched to same-class GT in confidence order. F1 is pooled across the four
classes; an entirely empty truth/prediction pair scores one. This is an explicit
surrogate, not per-frame AP. Main detection reporting remains globally sorted,
four-class BEV mAP, with null macro AP when a class has no GT. A hindsight choice
that maximizes frame F1 utility is **not an upper bound on global mAP**.

The per-request penalty is in F1 units. It is not measured latency, bytes or
energy. Select the experiment's penalty before final testing, or predeclare an
entire quality/request curve. Do not choose a favorable penalty after looking at
test results.

## Random controls

Every control uses the same frozen detector, frames, available sources and GT.

| Control | Behavior | Purpose |
|---|---|---|
| Independent random subsets | Each available partner is requested independently with probability 0.5 | Full action-space reference, including neither and both; expected budget only |
| Schedule-matched random | Copy the evaluated policy's request count on each frame; uniformly choose a feasible subset of that size | Test which partner to choose, conditional on the same query schedule |
| Budget-matched random | Shuffle request counts within receiver/feasible-action strata; uniformly choose feasible subsets of those sizes | Test timing and partner choice at the exact same total budget and 0/1/2 histogram |

The last two are **retrospective offline controls**, not deployable policies:
they use the evaluated policy's count schedule, never its quality, GT or measured
gains. They preserve counts in each receiver/availability stratum. They do not
preserve the Car2/Infra identity distribution, which is the quantity being tested.
Random seeds are predeclared (default 0–99); report every seed and the aggregate,
never the best seed. Reported standard deviations measure randomization spread,
not uncertainty across independent recordings.

Always-Car2, always-Infra, no acquisition and all sources remain required fixed
baselines. An entropy rule with two predeclared thresholds can stop, request one
random partner, or request all available partners. Its thresholds are diagnostic
defaults (0.5, 0.7), not calibrated settings. Its partner seed defaults to 42,
independent of the control seeds.

## Fit and replay

Cached analysis needs only the main NumPy environment; it does not load CoBEVT,
require torch/CUDA, or run the network again. The cache reader verifies native
frame identities, shared-GT fingerprints and completed-run state, and records
prediction-payload hashes for provenance.
It independently recomputes BEV matching and checks every original fixed
baseline's class support and AP at 0.3/0.5/0.7 within 1e-7 before proceeding.
Cache provenance retains source associations and integer timestamps. The
standalone evaluator uses convex polygon clipping without adding dependencies.

For an exploratory smoke replay on crossing1/2, choose a new output filename:

```bash
python scripts/urbaning_subsets.py compare \
  --runs runs/urbaning-stage1-cpu-mid10-001 \
  --diagnostic-cost 0.05 --output runs/urbaning-subsets-smoke.json
```

The report includes a clearly separated, **non-deployable hindsight F1 reference**
using GT to select actions. It must not be described as a trained acquisition
policy or evidence of pre-query prediction accuracy. Exploratory replay without
a frozen validated model rejects crossing3.

After collecting caches on separate original recordings:

```bash
python scripts/urbaning_subsets.py fit \
  --train-runs runs/acquisition-train-sequence \
  --validation-runs runs/acquisition-validation-sequence \
  --request-cost 0.05 --output models/urbaning/joint-gain.json

python scripts/urbaning_subsets.py compare \
  --runs runs/held-out-crossing3-sequence \
  --model models/urbaning/joint-gain.json --output runs/joint-gain-evaluation.json
```

Paths above denote caches that must actually be collected; they are not bundled
data. Output parent directories must exist. Fitting requires examples for all
three acquisition heads. Feature normalization uses training data only; ridge
regularization is selected on validation mean F1 utility. The request penalty is
retained in the exported model, not replaced during replay. Fit/validation reject
crossing3 and overlapping original recording IDs, even if sequence segment or
crossing suffixes differ. Evaluation rejects records used for either fitting or
selection. The detector identity must match across caches and the gain model.
The detector itself may have seen crossing1/2 during its original training; these
guards separate policy recordings and do not change detector provenance.

The `phdsim urbaning subsets` command exposes the same fit/compare entry points.
For new stage 1 counterfactual runs, `--acquisition-model` loads a frozen gain
model and records its decisions using only Car1 scores/entropy and availability.
It remains offline counterfactual evaluation, not an online transport system.
Both this path and cached replay use the same selector and recording guards.

## Completed diagnostic check

For source frames 101–110 of the existing crossing1 recording, with a diagnostic
penalty of 0.05 per bundle:

| Reference | BEV mAP@0.5 | Total partner requests over 10 frames |
|---|---:|---:|
| Always Infra | 47.53% | 10 |
| All sources | 53.21% | 20 |
| Entropy subset rule, partner seed 42 | 42.04% | 10 |
| Schedule-matched random, 100 seeds | 42.05% ± 1.87 p.p. | 10 in every seed |
| Non-deployable hindsight F1 utility reference | 52.16% | 17 |
| Random matched to hindsight's schedule | 50.47% ± 1.00 p.p. | 17 in every seed |
| Random matched to hindsight's count distribution | 49.90% ± 1.24 p.p. | 17 in every seed |

The hindsight reference chooses both in seven frames and Infra in three. It
does not choose Car2-only or no acquisition in this particular fragment; these
actions are supported and verified with known fixtures. This result establishes
neither learned-policy quality nor significance. In particular, the entropy rule
does not demonstrate an advantage over random, and always-Infra is stronger at
the one-request budget in this fragment. The complete 20-frame replay also
passed all baseline metric checks. No new detector inference was run.

Tests cover all four decisions, complementary joint gains, missing sources,
order-independent seeds, exact matched budgets, known rotated-box IoU and AP,
recording leakage guards, corrupted caches, and fit/export/replay on synthetic
recordings. Current environment: 19 UrbanIng tests passed and 6 optional
torch/catalog/integration tests skipped. Real trained-policy inference through
CoBEVT has not been revalidated in this environment.

See [completed detector pilot](URBANING_EXPERIMENTS.md) and
[stage 1 model protocol](URBANING_STAGE1.md).
