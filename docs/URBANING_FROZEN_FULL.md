# Frozen regional and tree policies on full crossing3

Completed on Ares on 2026-11-03: **job 21578375, 6m24s, exit 0**. This replay evaluates the two
unchanged validation-stage models on all seven completed crossing3 caches:
1400 frame records, five original recording groups. Crossing3 has already been
inspected: this is an expanded frozen-policy evaluation, not a new blind test.

## Verified full results

Uploaded `urbaning-frozen-full.zip`: 3,175,911 bytes; SHA256
`e7070e7bfc4743a7bba90310ce3a39ba893281c62c6f7c0e2a05c6c56472e802`.
Archive CRC/member hashes and 1400 prediction bindings passed. The uploaded
portable statistics reproduced all eight policies in both AP orders, and seed
42 for each pure random probability. Original matched controls retain exact
request totals and 0/1/2 histograms.

Primary global-sort four-class BEV mAP@.5:

| Policy | mAP (%) | Requests | Savings versus ALWAYS (%) |
| --- | ---: | ---: | ---: |
| Car1 | 23.9064 | 0 | 100.00 |
| Infra | 31.7422 | 1267 | 37.68 |
| Pure random p=.5, mean of 100 | 28.9725 | 1016.32 | 50.01 |
| Pure random p=.75, mean of 100 | 31.4119 | 1523.43 | 25.06 |
| Pure random p=.9, mean of 100 | 32.8147 | 1829.68 | 10.00 |
| GainEgo | 33.1274 | 1838 | 9.59 |
| GainGeometry | 32.2393 | 1533 | 24.59 |
| Regional frozen prototype | 32.3282 | 1401 | 31.09 |
| Tree frozen prototype | 32.5766 | 1488 | 26.81 |
| ALWAYS | 33.7102 | 2033 | 0.00 |

Both new policies outperform the prior GainGeometry point with fewer requests.
Regional saves 632 requests versus ALWAYS at a 1.3820pp mAP reduction; tree saves
545 at a 1.1335pp reduction. Pure p=.75 is lower in mAP and higher in mean requests
than either model; this is descriptive comparison of observed costs.

At exactly equal budgets, the original budget-random means are 31.9546%
(regional, 1401 requests) and 32.2086% (tree, 1488 requests). Model advantages are
**.3736pp** and **.3681pp**, above all 100 respective random draws. Schedule-random
means are 32.2034% and 32.3202%; advantages .1248pp (86/100 draws below regional)
and .2565pp (100/100 below tree, with a near tie against its best draw).
These draws do not establish generalization or a recording-level p-value.

Action interpretation matters. On the 722 both-available frames, tree chooses
Infra alone 545 times and both 177; it never declines all peers or chooses only
Car2. It always queries whichever sole partner is available. Regional chooses
Infra 566, Car2 60, both 93, neither 3. Thus tree mainly adds Car2 to an Infra
preference; this is not evidence of spatial information-gap reasoning.

An **additional post-hoc descriptive control**, not part of the frozen protocol,
retains Infra priority and randomizes the moments of extra Car2 requests:
query Infra whenever available, otherwise available Car2 (base 1311 requests),
then select uniformly without replacement 90 or 177 of the 722 both-available
frames for Car2. Exact budgets are borrowed from the frozen policies, so this
remains retrospective. A deterministic SHA256 ranking of
`infra-priority:SEED:NATIVE_FRAME_KEY`, seeds 0–99, uses no GT or prediction.
Mean global mAP is **32.1277% at 1401** and **32.3434% at 1488**. Regional/tree
retain **.2006pp/.2332pp**, above all 100 respective draws. Preference for Infra
explains part of the original random gap; a modest residual remains in this
inspected sample. No training or threshold selection occurred in this analysis.

Class AP@.5 (%), with the same confidence ordering:

| Class | Car1 | Infra | ALWAYS | Regional | Tree |
| --- | ---: | ---: | ---: | ---: | ---: |
| Vehicle | 44.2226 | 60.0136 | 63.6482 | 61.5400 | 62.0076 |
| Heavy_Vehicle | 25.3788 | 33.4749 | 33.1881 | 33.6171 | 33.6025 |
| 2Wheeler | 25.1653 | 28.9349 | 32.5086 | 29.9320 | 30.3409 |
| Pedestrian | .8589 | 4.5454 | 5.4957 | 4.2238 | 4.3556 |

Both models are below Infra-only for pedestrians and slightly above ALWAYS for
heavy vehicles. Both beat ALWAYS on only 2/7 sequences, not uniformly across
recordings. Seven sequences come from five original recording groups; global
AP is not an average of sequence AP. F1 remains separate: regional 52.2523%
versus budget-random mean 52.3311%, tree 52.5964% versus 52.6563%. Better AP does
not imply better F1. These are LiDAR/CoBEVT results, not all authors' methods or
RGB/thermal fusion. The existing regional pooling limitation remains.

No detector inference, fitting, threshold selection, geometry regeneration,
package installation or upstream imports occur. The shared environment is not
modified. Missing or changed caches fail explicitly rather than starting a
detector. The separate train/validation AP export still rejects crossing3.

## Frozen inputs

`urbaning-frozen-full-inputs-001.zip` contains the original bytes of the full
policy report, tree model, regional policy and regional validation report.
It is external research data and must not be committed to Git.

- ZIP: **1,530,914 bytes**; SHA256
  `5e02364687ea3e39e3d79d6ea47b3bb6ed11ed057e53b110dc1c4fa35e826347`.
- Tree model SHA256:
  `6c12e62e7c9f60365ae3d66b724c8eabf1e5953452add9f87598402ea924c347`.
- Regional: existing full 46-feature linear predictor, alpha .1; whole-frame
  subset selection with the already selected error-count penalty **8**.
- Tree: existing boosted geometry predictor, 32 Car1/pose features; the already
  selected F1-gain request penalty **.05**.
- Both models retain training groups `20241126_0001`, `20241126_0017` and
  validation group `20241126_0004`. No crossing3 fitting is permitted.

The two penalties have different units; they are not interchangeable. Neither
model is being retrained to optimize AP. Actual regional predictions reproduced
all 200 original validation choices exactly under NumPy 1.26.4 before handoff.

The regional model remains the audited prototype: summing affine cell outputs
can lose spatial binding. It chooses whole-frame partner subsets, not regional
transmissions. An empty detection cell is not an observed information gap;
Infra geometry is a site-origin proxy, not measured sensor visibility.

## Measurement

The main report and readable table use **four-class BEV mAP@.5 with global
confidence sorting**, requests and savings versus querying all available peers.
Class AP at .3/.5/.7 and the authors' default frame-order AP are saved separately.
Mean-frame micro F1 and F1 utility remain diagnostic fields.

Main comparisons: Car1; available Car2/Infra baselines; **pure independent
random**; the prior GainEgo/Geometry policies; regional; tree; ALWAYS. Random
draws each available peer independently per frame. At p=.5 this is uniform over
feasible subsets. The predeclared p=.5/.75/.9 curve uses seeds 0–99; no p is
selected from test performance. Comparisons at different costs alone cannot
establish better learned selection. Matched-budget and matched-schedule controls
are secondary retrospective controls. Randomization spread is not a confidence
interval over independent recordings.

Run/trace/pose/completion and prediction hashes must match the previous full
report. The four fixed baselines and both previous learned policies must
reproduce their original class AP in **both AP orders**; the p=.5 random replay
must also reproduce all 100 prior seeds. Model functions receive only Car1
detections/entropy and explicit peer metadata. GT and partner outcomes remain
offline evaluation data.

## Run on Ares

Download the frozen input ZIP to the Mac, copy it to
`$WORK/inputs/urbaning-frozen-full-inputs-001.zip`, and submit from the new checkout:

```bash
sbatch -A plgkgacq-cpu scripts/slurm/urbaning_frozen_full.sbatch \
  /net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work/inputs/urbaning-frozen-full-inputs-001.zip \
  5e02364687ea3e39e3d79d6ea47b3bb6ed11ed057e53b110dc1c4fa35e826347
```

The batch requests four CPUs, 12 GB RAM and a **two-hour maximum**, not a runtime
prediction. No scikit-learn installation is needed: JSON tree prediction uses
NumPy. Existing caches and poses are read from
`$WORK/phdsim/runs/urbaning-full-policies-001`. Outputs go into the new directory
`$WORK/phdsim/runs/urbaning-frozen-full-JOBID`.

Early `PRIMARY` log lines show policy mAP and requests before random controls.
The completed artifact is `urbaning-frozen-full.zip`, containing:

- `RESULTS.md`: main mAP/request/savings table with pure random visible;
- `report.json`: both AP orders, per-class and per-sequence policy results,
  all random seeds, source hashes and frozen frame choices;
- `frozen-choices.json`: checkpoint written before random controls;
- `offline-statistics.jsonl`: portable full-test per-action detection statistics
  for subsequent replay without the detector or original NPZ caches;
- `files.json`: member hashes; the final ZIP CRC, byte size and SHA256 are checked
  and printed before `DONE`.

## Validation of the implementation

An end-to-end fixture checks both models, both AP orders, pure random, parity,
secondary controls and portable output with detector/sklearn imports blocked.
Negative cases reject altered model costs, feature order, recording groups,
input archive hashes, cache hashes, prediction bindings and prior AP.
The UrbanIng suite passes 82 tests (6 optional skips); the new three tests also
pass with the Ares-compatible NumPy 1.26.4 runtime. These checks validate the
runner; they do not constitute full crossing3 results for these two models.
