# Fixed-grid regional training data

Prepared on 2026-11-03. This exports **inputs and offline supervision**, not a
trained acquisition policy or a performance improvement. The next stage can
learn where each partner is useful using only pre-query Car1 evidence.

## Fixed data and boundaries

The Ares job reuses the two original training caches (400 frames total) and one
validation cache (200 frames) plus their existing pose sidecars:

- Train: `20241126_0017_crossing1_00`, `20241126_0001_crossing2_00`.
- Validation: `20241126_0004_crossing2_00`.

It rejects crossing3 and original-recording overlap from headers before loading
predictions. There is no inference, fitting, upstream import, package installation
or network access. It uses the NumPy/PyYAML/Matplotlib container environment
already verified by inspection job 21574240. Source caches, trained models and
previous reports are preserved.

Each frame has **400 fixed 10m x 10m cells** covering `[-100,100)` in both Car1
BEV coordinates, plus **one overflow cell**. Cell index is `ix * 20 + iy`.
Box BEV centroids determine cell membership. The overflow cell preserves eligible
objects/predictions with centroids outside the grid; they are not clipped into
edge cells or discarded. Its center `[0,0]` is a placeholder with an explicit
overflow flag, not a physical location. Peer-relative geometry is zero there.
All cells, including empty ones, are retained without GT-driven sampling.

There remain only **two original training recordings and one validation
recording**. Cells and adjacent frames are correlated; the expanded array size
does not create independent recordings. Future model selection must retain this
recording split. Do not interpret an empty detection cell as observed free space,
an occlusion or a calibrated uncertainty estimate.

## Pre-query inputs

The pure `learning/urbaning_regions.py` builder accepts only Car1 boxes,
scores/classes and entropy, available source IDs, and explicit peer-to-Car1 poses.
It has no interface for GT, peer predictions, point clouds or teacher-selected
regions. The ordered 46 input columns are stored in the report:

- Cell center/radius, overflow indicator and Car1 entropy.
- Local detection count, mean/minimum/std confidence, count with score below
  .5, and a no-detection indicator.
- Counts, mean/minimum confidence and low-score counts separately for four classes.
- 3x3-neighborhood counts, mean confidence and low-score count (no grid wrapping).
- Per peer: availability, offsets/distance to the cell, heading sine/cosine,
  view-angle cosine proxy and whether the metadata origin lies inside the grid.

All cached Car1 detections contribute input evidence. The original evaluator's
radius filter separately defines eligible **targets**. Infra pose remains the
bundled site's coordinate origin, not an individual pole or visibility estimate.
Pose sharing is assumed; native associations are retained without certifying
causal online capture/availability timing. Frame keys are join metadata, not
learning features.

## Offline targets and conservation

The existing reader first reproduces the original baseline AP and validates GT,
cache/fallback consistency and trace-bound geometry. The object-index matcher
from the inspection stage must reproduce each frame's F1.

Matching is performed **globally before regional assignment**, using the frozen
same-class, confidence-ordered, greedy BEV IoU .5 protocol and corner-radius
filter. TP/FN are assigned by GT center; unmatched FP by prediction center.
This prevents a match straddling a cell boundary from becoming an artificial
FP/FN pair. Summing all cells/classes, including overflow, must reproduce exact
frame TP/FP/FN and F1 for every feasible action.

Targets keep four canonical actions (Car1, Car1+Car2, Car1+Infra, both), four
classes and three counts (TP, FP, FN). For each action they also store:

- Count deltas **action minus Car1**, separately by class and cell.
- GT recovered relative to Car1 and GT lost relative to Car1. Their difference
  must equal the TP delta in every cell/class.
- Common per-cell GT counts and an explicit action-availability mask.

Unavailable actions are **not** duplicated fallback training examples. Their
counts/recovered/lost targets are -1, deltas zero and mask false; future fitting
must use that mask. The mask itself is allowed pre-query metadata.

The summary/map uses **Car1 (FP+FN) minus action (FP+FN)** as a descriptive,
additive error-reduction label: positive means help, negative harm. This is not
AP, local F1 or a newly selected acquisition objective. FP deltas are net count
changes; individual FP identities are not tracked between fusion outputs.

Do not sum or average per-cell F1. Aggregate TP/FP/FN first. The earlier cost
.05 applies **once per requested peer per frame**, not once per cell. Regional
supervision does not yet establish a whole-frame acquisition policy.

Each target action is the outcome of **whole-frame partner fusion**. It does
not establish the result of requesting only that spatial tile. Mixing regional
outcomes from different actions is not an evaluated detector/fusion protocol.
The first future regional learner may still choose one whole-frame subset.

## Output

Each split/sequence directory contains:

| File | Contents |
|---|---|
| `inputs.npz` | `features[frame,401,46]`, action mask, join keys, cell centers |
| `offline-targets.npz` | `counts/delta_vs_ego[frame,401,4,4,3]`, recovered/lost GT, GT counts, mask and keys |
| `frames.jsonl` | Original frame/recording identities, native associations and payload/GT hashes |
| `summary.json` | Availability, empty input cells, positive/zero/negative label counts, overflow totals |
| `regional-example.png` | Validation only: local low-score map and three offline error-reduction maps |

The validation example is fixed source frame `000161` when present, otherwise
the middle frame. Its selection is independent of target values. Maps omit
overflow spatially, but all overflow counts are retained and reported.
`regional-dataset-report.json` records feature/axis definitions, hashes, detector,
code/runtime identity, grouping and limitations. All files are bundled into
`urbaning-regional-dataset.zip`. NumPy arrays require no pickle to load.

## Run

Submit from a separate checkout:

```bash
sbatch -A plgkgacq-cpu scripts/slurm/urbaning_regional_dataset.sbatch
```

The job reserves 4 CPUs, 12 GB and a one-hour limit. It prints VERIFY and REGIONS
progress every 25 frames. Actual Ares runtime is not yet measured. Default output
is `phdsim-work/phdsim/runs/urbaning-regional-dataset-001`; existing output is
never overwritten. For a preserved failed attempt, use a fresh absolute
`URBANING_REGIONAL_OUTPUT` directory.

Download on the Mac:

```bash
mkdir -p ~/Documents/phdsim-results/urbaning-regional-dataset-001
scp plgrajczykjan@ares.cyfronet.pl:/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work/phdsim/runs/urbaning-regional-dataset-001/urbaning-regional-dataset.zip \
  ~/Documents/phdsim-results/urbaning-regional-dataset-001/
```

Inspect the report and validation maps before fitting a model. In particular,
check sparse/negative targets and cell-class imbalance. Raw LiDAR observability,
RGB/thermal, sensor-specific transport and online cost measurements remain
separate later extensions.
