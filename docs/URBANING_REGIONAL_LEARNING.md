# Regional usefulness regression and feature ablations

**Audit status (2026-11-03): development prototype.** The 23.4% number is only
prediction MSE reduction. The subsequent affine predictor plus sum-pooling
policy loses spatial binding; no acquisition advantage is established. See
[audit findings and artifact repair](URBANING_AUDIT_2026-11-03.md).

This is a development experiment on the verified regional dataset, with no
detector calls. It trains on two original recordings (400 frames) and selects
hyperparameters on one previously inspected validation recording (200 frames).
It rejects crossing3 and recording overlap before opening NPZ arrays. It is not
an independent generalization estimate or an evaluated acquisition policy.

## Prediction target and boundary

For each 10m region and each of four classes, predict signed error reduction:
`gain = -(delta_FP + delta_FN)`. Positive means fewer errors than Car1 alone;
negative means harm. This combines missed objects and false alarms; it is not
the number of recovered objects, AP, F1, probability or visibility.

Three independent action heads predict Car1+Car2, Car1+Infra, and both. The joint
head is supervised directly, not obtained by adding single-peer outcomes. Each
uses only frames where that action is available. All 401 cells, including
overflow and cells with no Car1 detection, remain in training/evaluation.
Unavailable targets are never included as zero-gain examples.

The inference module takes only the 46 ordered input features and public
availability. GT, partner predictions and target counts are never accepted by
the prediction interface. The experimental runner loads offline labels for
training/scoring and verifies file hashes, input allowlist, keys, masks, source
identities, count conservation and recovery/loss identities. Source and dataset
hashes are saved in the report.

## Fixed feature comparison

All groups are manually designed hypotheses, not features prescribed by the
UrbanIng paper. Availability and an overflow indicator are retained throughout.

| Profile | Inputs | Count |
|---|---|---:|
| geometry | Cell position/radius, peer geometry and availability | 20 |
| local | Car1 entropy and aggregate local detection/confidence summaries, availability | 10 |
| geometry_local | Geometry and aggregate local evidence | 27 |
| geometry_local_neighbors | Previous plus 3x3-neighborhood summaries | 30 |
| full | Previous plus class-specific detection/confidence summaries | 46 |

Each action uses training-only standardization. Ridge minimizes mean squared
error plus `alpha * ||weights||²`, with an unpenalized intercept. The fixed grid
is `.01, .1, 1`; each profile selects its alpha by validation macro MSE, giving
equal weight to the 12 available action/class heads. The first candidate wins
exact ties. Signed predictions are never clipped. Baselines are zero everywhere
and a training-only mean per action/class. No label-based resampling occurs.

The report includes all-cell and changed/positive/negative/neutral MSE/MAE,
per-class results, and Car1-empty/nonempty strata. GT defines outcome strata
only during scoring. Sparse unchanged labels can conceal failure on important
regions; no all-cell accuracy headline or cell-level significance claim is used.

A secondary fixed top-10 region ranking diagnostic excludes overflow and sums
actual signed gain over the ten highest predicted regions per frame/action.
Stable grid order breaks ties. Uniform random expected gain is exactly 10/400
of the actual total; the GT top-10 is a privileged reference. These are region
ranking controls, **not** random partner schedules or communication-cost controls.
The fixed example uses validation frame 161 if present, otherwise its midpoint;
it is not selected by prediction quality.

## Observed development result, 2026-11-03

The uploaded dataset ZIP passed all bindings and conservation checks. NumPy-only
training/scoring completed locally in approximately five seconds. Runs with
NumPy 2.3.5 and Ares-compatible 1.26.4 selected the same hyperparameters and
agreed numerically to floating-point precision. No Ares job was submitted.

| Profile | Selected alpha | Validation macro MSE |
|---|---:|---:|
| zero | — | .049041 |
| training mean | — | .048335 |
| geometry | .1 | .047468 |
| local | .01 | .041654 |
| geometry_local | .01 | .041330 |
| geometry_local_neighbors | .01 | .041260 |
| full | .1 | .037557 |

Full features reduce this regression error by 23.4% relative to zero. That is
**not** a 23.4% detection improvement. Changed-cell macro MSE improves from
1.562838 to 1.131719, but negative-gain MSE worsens from 1.278871 to 1.602021:
the model still tends to predict benefit where a partner actually harms.

Most improvement is in cells with existing Car1 detections. For Car1-empty
physical cells, total-class gain MSE changes only .031828→.031889 (Car2),
.064545→.063579 (Infra), .069426→.068208 (both), versus zero. The central goal
of recognizing missing information where Car1 detects nothing remains open.
Geometry adds little beyond local evidence in this linear pilot, and the
46-feature model does not win every ranking diagnostic. No post-result tuning
or new feature search is included in this experiment.

## Run and preserve

From this checkout, with NumPy and Matplotlib installed:

```bash
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4 \
python scripts/urbaning_regional_learning.py \
  --dataset /path/to/urbaning-regional-dataset.zip \
  --output-dir /new/output/directory
```

Optional Ares reproduction from a separate checkout:

```bash
sbatch -A plgkgacq-cpu scripts/slurm/urbaning_regional_learning.sbatch
```

The output directory must not exist. The ZIP contains five JSON models,
validation predictions/identities/masks, a fixed actual/predicted map, a full
JSON report and README. No data, models or generated artifacts belong in Git.

Targets describe whole-frame fusion. Do not mix cell outcomes to simulate a
new detector, charge the .05 peer/frame request cost per cell, or feed these
count reductions into the existing F1-gain policy. A future acquisition stage
must specify its aggregation/objective and evaluate actual feasible actions
with fair budget controls. RGB/thermal, LiDAR coverage and causal metadata
timing remain unimplemented.
