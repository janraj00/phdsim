# Frozen spatial policies on the same full crossing3 inventory

Status: **prepared and tested, not yet submitted from this session** (2026-11-04).
User authorized evaluating the new spatial policies on the same 1400 crossing3
frames as the older regional/tree results. The seven sequences are fixed in
`urbaning_frozen_full.SEQUENCES`, 200 frames each, five original recording groups.
These recordings have already been inspected; this is not a newly blind test.

## Fixed inputs and policy boundary

The runner reads the Ares validation job **21586379** output in place:

```
phdsim/runs/urbaning-gap-acquisition-21586379/urbaning-gap-acquisition-validation.zip
SHA256 78c2e20d12acb3334931d0ca763e0cf4d414f2ba7779ef0c67e95869416e8786
```

Its original frozen deployment packet SHA256 is
`c8a5ea84e6fb74a45b25a45573d8f6d60408e2002080da50cbf38231c8828171`.
All 18 saved profile/aggregation/cost configurations are retained. The primary
transfer point is declared before crossing3 reads: geometry, ten gap-selected
cells, error cost .5 (the validation-cap1.5 configuration). Other configurations
are reported without choosing a new winner or cost on crossing3.

The historical caps .5/1/1.5 requests per validation frame are labels only.
No crossing3 budget is imposed or used to retune thresholds. Actual requests
may differ from validation or exceed those historic caps on these recordings.

Policy inputs are Car1 boxes, scores and entropy plus assumed pre-query peer
poses/availability. Only `ego_boxes` and `ego_scores` are loaded from each raw
cached NPZ. GT and peer output arrays are not read by the public feature adapter.
Offline portable detection statistics are used separately for evaluation.
Ten cells are selected from all 400, with the same selected cells used for each
subset head. One whole-frame partner subset wins; no ROI payload selection,
no mixing boxes from different actions, no per-cell communication charge.
Infra coordinates remain a site-origin proxy, not measured sensor placement.

## Reuse of previous evaluation

The same full-frame portable outcomes already exist in Ares job **21578375**:

```
phdsim/runs/urbaning-frozen-full-21578375/urbaning-frozen-full.zip
SHA256 e7070e7bfc4743a7bba90310ce3a39ba893281c62c6f7c0e2a05c6c56472e802
```

Before new features are computed, verify outer/member hashes, exact inventory,
detector/payload identities, ordered frame keys and all eight historical
policies' AP in both modes. Raw source NPZ hashes, run/trace headers and pose
sidecar hashes must agree with those portable outcomes. Missing/stale inputs
fail; the runner cannot launch inference or download replacements.

The new policies use the NumPy-only portable forests. No sklearn, detector,
Torch/Open3D imports, fitting, installs or shared environment edits are required.
NumPy **1.26.4** is required for AP confidence-tie parity.

## Comparison/report protocol

Primary: four-class global-confidence-sort BEV mAP@.5, actual requests, savings
and mAP loss versus ALWAYS. Keep authors' default-order AP separate. Include
class AP, per-sequence results and historical policies on the same outcomes.
No validation numbers are mixed into the full crossing3 result table.

Pure random independently asks each available peer with fixed p=.25/.5/.75/.9,
seeds 0–99. Existing .5/.75/.9 100-seed results are reused after reproducing
seeds 0/99 in both AP orders; .25 is newly replayed. Secondary controls uniformly
sample exactly each unique new policy query total across all feasible
frame/peer query events, without the model's action schedule or histogram.
These exact-total controls use retrospective totals and are not an online rule.
Seed spread is not a confidence interval over independent recordings.
Request count is not bytes or latency. F1 remains secondary and does not select
any setting in this job.

## Submit without uploading any new files

The worker script hardcodes the two verified existing Ares input paths and hashes.
From the original repository root on Ares, fetch the branch and create a fresh
worktree at its reviewed commit. Submit from the new worktree root:

```bash
git fetch origin codex/urbaning-gap-full
git worktree add --detach ../phdsim-gap-full FETCH_HEAD
cd ../phdsim-gap-full
sbatch -A plgkgacq-cpu scripts/slurm/urbaning_gap_full.sbatch
```

Resources: 4 CPUs / 12 GB / **4-hour upper limit**, not an estimated duration.
The job uses the established Singularity Python wrapper, never the login-node
interpreter. Progress prints old-policy AP parity, spatial predictions/reuse
for each sequence/profile, new policy AP/requests, and random seed counters.
Actual runtime has not yet been measured.

Output defaults to `phdsim/runs/urbaning-gap-full-JOBID/`. The final downloadable
`urbaning-gap-full.zip` contains `report.json`, `protocol.json`,
`frozen-choices.json`, `WYNIKI_PL.md`, hash manifest and all frozen spatial score
NPZ checkpoints for later analysis without recomputing the forests.

To resume a stopped job, pass its same absolute output directory as the first
argument to `sbatch ... urbaning_gap_full.sbatch`. A lock prevents concurrent
writers. Protocol/source/model hashes and public features bind checkpoints;
spatial scores and per-action/per-random-seed AP results resume independently.
Changed protocol, inputs or implementation refuse resumption. Keep the exact
same commit for a resume. Final ZIP replacement is atomic.

## Local validation

Four focused end-to-end/boundary tests cover complete fixture replay and
resumption, portable operation with sklearn/detector imports blocked, original
AP parity, early rejection of a wrong development hash, changed poses, and
instrumented public NPZ access limited to Car1 boxes/scores. Gap-related tests
and shell syntax passed. On the real portable inputs, the original three model
hashes/all18 frozen settings loaded, and all eight older policies reproduced
both AP modes on all1400 frames. The full raw Car1/pose caches reside on Ares;
no new real1400 spatial policy result has been computed locally.
