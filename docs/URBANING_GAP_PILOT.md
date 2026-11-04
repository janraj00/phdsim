# Region gap and source pilot

Completed locally on 2026-11-04 using the existing verified regional ZIP.
No Ares submission, detector inference, new observations or crossing3 payload
reads. Training: 400 frames in two original recordings. Validation: 200 frames
in one previously inspected recording. This is a development diagnostic, not
an independent final test or a new acquisition mAP result.

## Frozen comparison

All variants use ExtraTrees with 64 trees, maximum depth 8, minimum leaf size
100, all features available at each split, no bootstrap, seed 42 and four CPU
workers. NumPy 1.26.4 / scikit-learn 1.8.0 reuse the existing isolated runtime;
no environment was modified. There is no parameter grid or validation-based
selection. All three profiles are retained:

- Geometry: cell coordinates/radius/overflow flag and available partner poses
  (20 ordered features).
- Local: Car1 entropy, cell/class detection summaries and neighbors (26).
- Combined: all 46 original public features, allowing nonlinear interactions.

Only the 400 spatial cells are ranked; the overflow bucket is excluded.
For each profile, fit a binary gap forest (at least one Car1 FN in cell), and
three separate signed local FP+FN reduction forests for Car2, Infra and both.
The joint head is directly supervised rather than a sum of singleton heads.
Models receive no GT class, GT boxes, missed-object identity or peer predictions
at prediction time. Availability masks exclude infeasible heads.

The exact unchanged train/validation manifests, model JSON hashes, source hashes
and runtime are stored in the artifact. Portable NumPy-only forest prediction
reproduced native sklearn outputs within 1e-12 on a fixed training-only sample.
No pickle files are loaded or needed for prediction.

## Gap localization results

Predeclared K=10; lexical cell index breaks prediction ties without consulting
labels. Each row is a mean number of selected cells with >=1 FN, out of ten
selected cells per frame. The empty-only column independently ranks only cells
with no Car1 detection centroid; it is not a subset of the all-cell top10.

| Features | Correct top10 fields: full grid | Correct top10: empty-only |
| --- | ---: | ---: |
| Uniform random, exact expectation | .672 | .386 |
| Geometry | 3.585 | 2.815 |
| Local | 4.660 | 1.490 |
| Combined | 4.485 | 2.355 |

Local cues lead over the full grid. Geometry leads for completely empty
detection cells. Combined improves over local in empty cells but does not beat
geometry there, and does not beat local over the full grid. These findings must
not be presented as uniform superiority of combining the feature sets.

## Two-stage review of unchanged predictions

Regions are selected by predicted gap score, then the feasible subset with
highest predicted signed local gain is selected in each chosen region. A
success requires recovery of >=1 previously missed GT **and** strictly positive
local FP+FN reduction. Pure random uniformly selects ten distinct regions and
a feasible subset independently of the model; its exact expected precision is
reported without Monte Carlo noise. Same-region random-source control is
secondary and retains model-selected regions.

| Features | Successful proposals / 10 | Pure random / 10 | Same gap regions, random subset / 10 |
| --- | ---: | ---: | ---: |
| Geometry | 2.460 | .276 | 2.198 |
| Local | 2.045 | .276 | 1.750 |
| Combined | 2.220 | .276 | 1.940 |

On the full grid, this is 492, 409 and 444 successful proposals out of 2000.
For empty-only ranking the corresponding means are 1.845, .780 and 1.270;
pure random expectation .156. Geometry leads this two-stage diagnostic.

The initial signed-benefit heads were also separately ranked by their own
predicted gain, without requiring gap selection first. Positive FP+FN reduction
occurred in 33.00% / 71.60% / 72.15% of their top10 proposals, versus a pure
random expectation 5.41%. This is a different question: reducing false alarms
alone can count, so these values must not be described as missed-object
recoveries or conflated with the stricter two-stage table above.

## What has and has not been established

The pilot locates missed-object regions more often than uniform random on the
inspected validation recording, and offers modest extra source-selection value
beyond random subsets in the same selected regions. It does not establish a
physical visibility map, a calibrated epistemic-uncertainty estimate, a causal
explanation of failures or generalization to a new intersection.

The source outcomes are from **whole-frame fusion**. Different local outcomes
cannot be pasted together and treated as a valid detector prediction. Ten
region/subset proposals are not ten independent network requests. Both-partner
proposals are allowed and no communication penalty is imposed in this spatial
diagnostic. No new detection mAP, request savings or ROI-transmission result
has been computed. Original recording counts, not 160000 correlated training
cells, define the small experimental support.

The next experiment must map these frozen spatial predictions to 0/1/2
whole-frame partner requests, define and freeze costs/aggregation on development
data, evaluate mAP through the existing common AP evaluator, and retain pure
random plus Infra-priority controls. Previously inspected crossing3 cannot be
relabeled as a new blind test. More local evidence such as LiDAR density or
pre-NMS BEV objectness is a separate possible extension, not an input used here.

## Reproduce

```bash
PYTHONPATH=/path/to/isolated-dependencies:src \
  OPENBLAS_NUM_THREADS=4 OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 \
  python scripts/urbaning_gap_pilot.py \
  --dataset /path/to/urbaning-regional-dataset.zip \
  --output-dir /new/path/gap-pilot --cpu-threads 4

PYTHONPATH=/path/to/isolated-dependencies:src \
  python scripts/urbaning_gap_review.py \
  --pilot /new/path/gap-pilot \
  --dataset /path/to/urbaning-regional-dataset.zip \
  --output-dir /new/path/gap-review
```

Fit and serialization/parity/scoring elapsed 14.11s geometry, 8.38s local and
19.82s combined in this runtime. These timings are not detector latency.
Original immutable pilot archive: 4,983,594 bytes, SHA256
`056ec25fc70c9eb66128d65b4295fdbe37ca14e0bb24a14ae7566b9d3b419ab6`.
Review artifact including original weights/reports and Polish summary:
4,986,101 bytes, SHA256
`f269aec67685dfa6aed1fa194facdcfb984a0dab9e0bc518101ce8faea739f2d`.

Four focused tests cover deterministic ranking/random expectation, harmful and
unavailable outcomes, native/portable prediction and GT-free deployment API,
and the coupled recovery-plus-net-improvement success criterion. Dataset
crossing3/split/hash/count guards reuse the already tested regional loader.

References: [ExtraTreesClassifier](https://scikit-learn.org/1.8/modules/generated/sklearn.ensemble.ExtraTreesClassifier.html),
[ExtraTreesRegressor](https://scikit-learn.org/1.8/modules/generated/sklearn.ensemble.ExtraTreesRegressor.html).
