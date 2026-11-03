# Frozen regional and tree policies on full crossing3

Prepared on 2026-11-03; **not yet run on Ares**. This replay evaluates the two
unchanged validation-stage models on all seven completed crossing3 caches:
1400 frame records, five original recording groups. Crossing3 has already been
inspected: this is an expanded frozen-policy evaluation, not a new blind test.

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
