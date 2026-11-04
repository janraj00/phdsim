# Frozen spatial policies on the same full crossing3 inventory

Status: **Ares job 21586593 completed and results checked** (2026-11-04).
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

## Completed Ares replay — job 21586593

Completed in **8m16s**, Slurm exit0. Uploaded output SHA256
`82227530fb755da55bc516cc495ebeb70aaa9323a3e6adf892b13af3ee814869`,
14,679,451 bytes. CRC/all25 member hashes and implementation hashes passed.
All18 new policies' AP reproduced in both ordering modes and all25,200
decisions reproduced from frozen spatial score checkpoints. Original eight
policies reproduced against the previous portable1400 outcomes. Exact-total
random controls were independently checked at seeds0/99 in both AP modes.
This sampled check does not claim all100 seeds were rerun locally.

The predeclared primary transfer point (geometry/top10/cost.5) obtains
**32.6966% mAP / 1448 requests** on these same1400 frames. ALWAYS is
**33.7102% / 2033**: **585 requests saved (28.78%)**, **1.0136pp mAP loss**.
Compared with the old tree32.5766%/1488, the new point has **+.1200pp** mAP
and **40 fewer queries**. Compared with old regional32.3282%/1401 it has
+.3684pp mAP at47 more queries, not a dominance claim. Costs/weights were
unchanged from validation. No new full-test point was selected.

Pure independent random p=.75:31.4119%/1523.43; p=.9:32.8147%/1829.68.
Exactly1448 uniform random query events: mean31.0770%, range30.7649–31.3512%
over100 seeds. The policy is1.6196pp above that mean and above all100 draws.
This is conditional randomization evidence, not recording-level significance.
Historical budget/schedule-matched controls used a different constraint;
do not compare this1.6196pp gap with those older control gaps as a model gain.

### All frozen configurations and historical policies

All entries below use the same global-sort four-class BEV mAP@.5 on1400 frames.
Validation-cap suffixes are annotations, not imposed crossing3 query budgets.

| Policy | mAP (%) | Queries | Savings vs ALWAYS (%) | mAP loss vs ALWAYS (pp) |
|---|---:|---:|---:|---:|
| ego | 23.9064 | 0 | 100.00 | 9.8038 |
| vehicle_peer | 27.3463 | 766 | 62.32 | 6.3638 |
| infrastructure | 31.7422 | 1267 | 37.68 | 1.9680 |
| all | 33.7102 | 2033 | 0.00 | 0.0000 |
| gain_ego | 33.1274 | 1838 | 9.59 | 0.5828 |
| gain_geometry | 32.2393 | 1533 | 24.59 | 1.4709 |
| regional | 32.3282 | 1401 | 31.09 | 1.3819 |
| tree | 32.5766 | 1488 | 26.81 | 1.1335 |
| spatial_geometry_gap_top10_valcap0.5 | 27.9744 | 540 | 73.44 | 5.7358 |
| spatial_geometry_gap_top10_valcap1 | 32.2199 | 1306 | 35.76 | 1.4902 |
| spatial_geometry_gap_top10_valcap1.5 | 32.6966 | 1448 | 28.78 | 1.0136 |
| spatial_geometry_all_cells_valcap0.5 | 23.9064 | 0 | 100.00 | 9.8038 |
| spatial_geometry_all_cells_valcap1 | 30.5105 | 1183 | 41.81 | 3.1997 |
| spatial_geometry_all_cells_valcap1.5 | 32.3200 | 1402 | 31.04 | 1.3901 |
| spatial_local_gap_top10_valcap0.5 | 26.7019 | 517 | 74.57 | 7.0083 |
| spatial_local_gap_top10_valcap1 | 31.9069 | 1309 | 35.61 | 1.8033 |
| spatial_local_gap_top10_valcap1.5 | 32.5476 | 1515 | 25.48 | 1.1625 |
| spatial_local_all_cells_valcap0.5 | 23.9530 | 2 | 99.90 | 9.7571 |
| spatial_local_all_cells_valcap1 | 28.4728 | 668 | 67.14 | 5.2373 |
| spatial_local_all_cells_valcap1.5 | 31.8518 | 1301 | 36.01 | 1.8584 |
| spatial_combined_gap_top10_valcap0.5 | 28.6614 | 649 | 68.08 | 5.0487 |
| spatial_combined_gap_top10_valcap1 | 32.0733 | 1305 | 35.81 | 1.6369 |
| spatial_combined_gap_top10_valcap1.5 | 32.3681 | 1506 | 25.92 | 1.3420 |
| spatial_combined_all_cells_valcap0.5 | 24.1321 | 20 | 99.02 | 9.5780 |
| spatial_combined_all_cells_valcap1 | 31.3527 | 1179 | 42.01 | 2.3575 |
| spatial_combined_all_cells_valcap1.5 | 32.0883 | 1417 | 30.30 | 1.6218 |

### Action audit and limitations

Primary point: Car1+Car2 on71 frames, Car1+Infra on1103, both on137,
Car1 alone on89. All89 have no available partner. On the722 both-available
frames it chooses Car2 alone27 times, Infra alone558 and both137. Therefore
the585 savings consist of558 skipped Car2 queries and27 skipped Infra queries.
No learned abstention when a peer exists is demonstrated by this point.
The best transfer point uses geometry/availability, not Car1 detection scores;
its success is not evidence of local evidence-conditioned gap recognition.

Against the old tree, per-sequence mAP improves in3, ties in1 and drops in3
of7 sequences. These seven clips are only five original recording groups.
Class AP versus tree: Vehicle62.1375 vs62.0076; Heavy_Vehicle34.5598 vs33.6025;
2Wheeler29.6679 vs30.3409; Pedestrian4.4212 vs4.3556. Pedestrian remains below
Infra-only4.5454 and ALWAYS5.4957. Do not claim uniform class/recording gains.
No byte/latency gain, ROI transmission, causal visibility estimate or independent
new blind-test performance follows from these results. A strong Infra-priority
control at the same query count has not been evaluated for this new point.

## User-requested zero-cost diagnostic (2026-11-04)

After reviewing the full/hybrid results, the user explicitly asked about removing
query penalties. Read-only replay of the original frozen geometry gap/benefit
scores on the same1400 full frames, changing only cost .5 to0 (still top10/all400).
No retraining, detector or new cost search. Reproduced old policy AP first using
the original portable outcomes. This is a **post-hoc operating-point diagnostic**,
not a newly validation-selected configuration or blind-test result. Preserve
cost.5 as the original predeclared full replay point.

| Policy | Global-sort mAP@.5 (%) | Queries | Savings vs ALWAYS (%) | Loss vs ALWAYS (pp) |
|---|---:|---:|---:|---:|
| Original geometry/top10, cost .5 | 32.6966 | 1448 | 28.78 | 1.0136 |
| Same frozen model, cost0, post-hoc | 33.6741 | 1813 | 10.82 | .0361 |
| ALWAYS | 33.7102 | 2033 | 0 | 0 |

Zero penalty still omits220 possible queries. On the722 both-available frames,
it chooses Car2 alone18 times, Infra alone202 and both502. Total actions across
all1400: Car2/Infra/both/none =62/747/502/89. No-query cases still have no peer.
It prefers a single partner when the direct joint head predicts no additional
benefit or harm; zero penalty does not impose ALWAYS. Relative to cost.5,
365 frames add the second partner and365 additional queries are made.
The .0361pp global mAP gap is an observed average on these recordings, not
statistical equivalence/noninferiority or uniform per-class performance.
Upstream-default AP for this zero-cost diagnostic is24.5426%, kept separate.

On200 development validation frames, geometry/geometry and local/local at cost0
both equal ALWAYS exactly:37.6015%/334. The proposed local-gap/geometry-benefit
hybrid at cost0 is36.2489%/319; reverse pairing37.3157%/327. Do not mix those
200-frame values with full1400 numbers above. No production/default policy or
original frozen configuration file has been changed by this diagnostic.
