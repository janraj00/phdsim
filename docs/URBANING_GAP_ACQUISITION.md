# Frozen spatial scores to whole-frame acquisition — Ares validation replay

Status: **Ares validation replay completed and checked** (2026-11-04).
The user requested moving computation to Ares after the cloud conversation
was interrupted. Ares job **21586379** produced the verified output. This is the
200-frame crossing2 development validation, not the 1400-frame crossing3 replay.

## Fixed experiment

The three original ExtraTrees model profiles remain unchanged: geometry,
local Car1 evidence and their combination. Their existing validation predictions
are bound to the original detector, frame keys, payloads and frozen model hashes.
No training, detector inference, crossing3 access, installs or shared venv changes.

For each frame, compare two aggregation rules:

1. Select ten cells from all 400 by predicted Car1-gap score, and sum each
   feasible subset head's predicted signed FP+FN reduction over those same cells.
2. Sum over all 400 cells, as a pooling comparison.

Subtract the fixed cost per **actually requested peer**, once per whole frame.
Choose exactly one feasible action: Car1 alone, Car1+Car2, Car1+Infra, or all.
The joint head is supervised separately; it is not a sum of singleton heads.
There is no mixing detector boxes from different actions by cell and no region
transmission. Zero predicted gain is assigned to Car1 alone; ties favor fewer
requests, then the canonical action order.

Cost grid: **0, .25, .5, 1, 2, 4, 8, 16, 32, 64** predicted error-count units.
For each profile and aggregation, select maximum validation global-sort
four-class BEV mAP@.5 under each request cap: **.5, 1, 1.5 per frame**
(100/200/300 total on these frames). Ties favor fewer requests then grid order.
An unattainable cap is reported explicitly, not silently replaced. There is
no cross-profile winner selection. Save the protocol before candidate AP and
save deployable configurations/model bytes before random comparisons.

This selects costs on an already-inspected validation recording. It is
development evidence, not independent generalization. Learned gap/benefit
scores are policy inputs; GT and counterfactual detection outcomes remain
offline evaluation data. A cell without a Car1 detection is not an established
occluded/unobserved region. Infra positions retain the site-origin proxy caveat.

## Comparisons and reports

- Four canonical fixed baselines, with explicit unavailable-peer fallback.
- Infra when available, otherwise Car2; and the reversed priority.
- **Main random baseline:** independently ask each available peer with fixed
  p=.25/.5/.75/.9, seeds 0–99. Both/one/none are all possible.
- Secondary retrospective control: uniformly sample the same total number of
  feasible frame/peer queries without replacement, seeds 0–99. It receives only
  the scalar query count, never the model's timing or per-frame action histogram.
  This exact-total control is offline, not a claimed deployable method.

Primary measure: global-confidence-sort BEV mAP@.5, with requests, savings and
mAP loss versus ALWAYS. Both AP ordering modes and class AP are retained.
Default-order AP is separate; F1/old F1 utility are diagnostics and never select
costs here. Seed variation describes randomization on this recording, not
recording-level uncertainty. Requests do not measure bytes/latency.

Outputs: `protocol.json`, `report.json`, `selected-frozen-policies.json`,
`frozen-gap-acquisition-inputs.zip`, `WYNIKI_PL.md`, `files.json`, and the final
`urbaning-gap-acquisition-validation.zip`. The latter contains the deployable
frozen packet as well as results. No result or saving is established until
the real job completes.

## Input packet

`urbaning-gap-acquisition-inputs-001.zip`, **13,257,571 bytes**, SHA256:

```
c1e72f33bdbd61edab2773bac81d2f582b88ed4d625e9743c35ac194d8bb50ee
```

It embeds the original pilot ZIP, regional dataset ZIP and portable AP export
with individual hashes. Train frames are included only for source/baseline
verification; no refitting occurs. Staging verifies the outer SHA, exact members,
inner hashes, CRC, safe paths and size limit. Replay verifies frozen pilot files,
original baseline AP in both modes, detector/frame/payload/availability bindings.
The existing CPU container needs NumPy **1.26.4**, which preserves confidence-tie
AP parity. This runner does not need scikit-learn, Torch or Open3D.

## Submit on Ares

Download the input packet on the Mac, then use the file picker rather than an
assumed Downloads path:

```bash
ssh plgrajczykjan@ares.cyfronet.pl 'mkdir -p /net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work/inputs'
if URBANING_ZIP=$(osascript -e 'POSIX path of (choose file with prompt "Wybierz urbaning-gap-acquisition-inputs-001.zip")'); then
  scp "$URBANING_ZIP" plgrajczykjan@ares.cyfronet.pl:/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work/inputs/
fi
```

Use a fresh worktree at the reviewed gap-acquisition commit, then submit from
its root (fetching only does not update an existing worktree):

```bash
git fetch origin codex/urbaning-gap-acquisition
git worktree add --detach ../phdsim-gap-acquisition FETCH_HEAD
cd ../phdsim-gap-acquisition
sbatch -A plgkgacq-cpu scripts/slurm/urbaning_gap_acquisition.sbatch \
  /net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work/inputs/urbaning-gap-acquisition-inputs-001.zip \
  c1e72f33bdbd61edab2773bac81d2f582b88ed4d625e9743c35ac194d8bb50ee
```

The worker requests 4 CPUs / 12 GB / a 2-hour upper limit, not an estimated
duration. It uses the established `bin/urbaning-python.sh` worker wrapper.
Job elapsed time was not included in the supplied completion excerpt. Look for `REPLAYED`, `PURE RANDOM`,
`RANDOM n/100 seeds`, then final `DONE` and output SHA. This is cached AP replay,
not the previous multi-hour detector pass.

## Resume after interruption

Each distinct action list is checkpointed atomically, including each random
seed. A checkpoint binds the exact protocol, implementation hashes, input
hashes and action list; it also checks its stored metric hash. An output lock
rejects simultaneous workers using the same directory. A changed input/code/
protocol refuses resumption. Final archives are replaced atomically.

After the previous job stops, pass its **same output directory** as the third
argument to the same `sbatch` command. The directory is printed as `OUTPUT:`
and defaults to `.../phdsim/runs/urbaning-gap-acquisition-JOBID`. Reusing only
the same ZIP with no output argument starts a fresh directory. Old run outputs,
raw caches, model files and shared environments are preserved.

## Verification before submission

Five focused tests cover whole-frame selection, explicit joint benefit,
unavailable heads, independent fixed-total random support, checkpoint protocol/
action binding and tamper detection, verified staging/resumption and path
traversal rejection. Bash syntax passed. A real-input smoke test verified
train/validation baseline AP in both orders, all 200 validation payload/frame
bindings, one real action list's AP and checkpoint reuse. It did not perform
the full cost-grid/random experiment or select final policies.

## Completed Ares validation result (job 21586379)

The uploaded output passed SHA256/CRC and every member hash. ZIP SHA256
`78c2e20d12acb3334931d0ca763e0cf4d414f2ba7779ef0c67e95869416e8786`,
3,345,608 bytes. Original frozen model and deployment hashes match. All 60
candidate AP results reproduced in both ordering modes; all 18 selected
profile/aggregation/budget points reproduce the declared selection rule.
Random seeds 0 and 99 were independently replayed in both orders for every
pure-random probability and all 17 exact-total controls. This is a sampled
random-parity check, not a claim to rerun all 100 seeds locally.

All numbers below are **200-frame, previously inspected development validation**,
with costs selected on these same frames. They are not the older full crossing3
results, an independent test or a new blind evaluation. Main metric is global-sort
four-class BEV mAP@.5. No detector or fitting was repeated.

### Fixed and independent random references

| Policy | mAP (%) | Requests |
|---|---:|---:|
| ego | 21.5380 | 0 |
| vehicle_peer | 31.7884 | 200 |
| infrastructure | 29.7240 | 134 |
| all | 37.6015 | 334 |
| infrastructure_otherwise_other | 31.2461 | 200 |
| vehicle_peer_otherwise_other | 31.7884 | 200 |
| Independent random p=0.25, 100-seed mean | 25.7835 | 82.87 |
| Independent random p=0.5, 100-seed mean | 29.9324 | 166.12 |
| Independent random p=0.75, 100-seed mean | 33.9805 | 250.65 |
| Independent random p=0.9, 100-seed mean | 36.1704 | 300.48 |

### All predeclared budget selections

The same ten cells selected by the profile's predicted gap score are used for
all subset heads. The ten are selected from **all 400 geographic cells**, not
only cells without Car1 detections. Every outcome is one whole-frame fusion
action. A cell proposal is not charged as a separate query.

| Profile | Cells aggregated | Query cap | Error cost | mAP (%) | Requests | Savings vs ALWAYS (%) | mAP loss (pp) | Same-total random mAP mean (%) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Geometry | 10 gap-selected from 400 | 100 | 4 | 22.9719 | 35 | 89.52 | 14.6297 | 23.3495 |
| Geometry | 10 gap-selected from 400 | 200 | 1 | 30.9157 | 184 | 44.91 | 6.6858 | 30.8401 |
| Geometry | 10 gap-selected from 400 | 300 | 0.5 | 36.0361 | 271 | 18.86 | 1.5654 | 34.8337 |
| Geometry | All 400 | 100 | 32 | 21.5380 | 0 | 100.00 | 16.0635 | 21.5380 |
| Geometry | All 400 | 200 | 16 | 29.7240 | 134 | 59.88 | 7.8776 | 28.3366 |
| Geometry | All 400 | 300 | 8 | 31.5265 | 235 | 29.64 | 6.0751 | 33.1955 |
| Local Car1 evidence | 10 gap-selected from 400 | 100 | 8 | 27.7495 | 100 | 70.06 | 9.8520 | 26.6490 |
| Local Car1 evidence | 10 gap-selected from 400 | 200 | 4 | 31.2919 | 199 | 40.42 | 6.3096 | 31.6184 |
| Local Car1 evidence | 10 gap-selected from 400 | 300 | 2 | 35.4918 | 283 | 15.27 | 2.1097 | 35.4288 |
| Local Car1 evidence | All 400 | 100 | 32 | 21.7444 | 1 | 99.70 | 15.8571 | 21.5878 |
| Local Car1 evidence | All 400 | 200 | 16 | 30.5188 | 157 | 52.99 | 7.0827 | 29.4978 |
| Local Car1 evidence | All 400 | 300 | 8 | 34.7184 | 260 | 22.16 | 2.8831 | 34.3330 |
| Combined evidence | 10 gap-selected from 400 | 100 | 8 | 25.2640 | 79 | 76.35 | 12.3375 | 25.5644 |
| Combined evidence | 10 gap-selected from 400 | 200 | 4 | 30.9797 | 200 | 40.12 | 6.6218 | 31.4968 |
| Combined evidence | 10 gap-selected from 400 | 300 | 2 | 34.4460 | 252 | 24.55 | 3.1555 | 34.0264 |
| Combined evidence | All 400 | 100 | 32 | 21.5380 | 0 | 100.00 | 16.0635 | 21.5380 |
| Combined evidence | All 400 | 200 | 16 | 30.9285 | 165 | 50.60 | 6.6730 | 29.8699 |
| Combined evidence | All 400 | 300 | 8 | 33.0712 | 244 | 26.95 | 4.5303 | 33.6424 |

### Interpretation

Geometry with ten gap-selected cells, cost .5, is the highest-mAP selected
point under the 300-request cap: **36.0361% / 271 requests**. Versus ALWAYS
37.6015% / 334 it saves **63 (18.86%)** requests and loses **1.5654pp** mAP.
Its actions are Car1+Car2 on 75 frames, Car1+Infra on 54 and both on 71;
it never abstains on this recording. The 63 savings consist of choosing one
partner instead of both on 63 of the 134 both-available frames.

Same-total random mean is **34.8337%** at 271 queries: +1.2024pp for the
policy. All 100 random draws are below it (range 33.9581–35.7326%). This is
conditional randomization evidence on the same development recording, **not**
a recording-level significance test or selection-adjusted generalization claim.
The predeclared independent random p=.75 uses 250.65 queries for 33.9805%;
p=.9 uses 300.48 for 36.1704%. These have different budgets.

The local-evidence model was better at locating gaps in the earlier ranking
diagnostic, but does not produce the best acquisition mAP here. Combined inputs
do not uniformly help. At about 200 queries, Car1+Car2 (31.7884%, 200 queries)
dominates combined/top10 (30.9797%, 200) and nearly matches the cost of local/
top10 (31.2919%, 199). Do not present every learned point as beneficial.

The geometry/top10 point improves Heavy_Vehicle AP versus ALWAYS
(36.6050% vs 35.1632%) but reduces Vehicle (76.5693% vs 78.1855%),
2Wheeler (24.5183% vs 29.3058%) and Pedestrian (6.4520% vs 7.7517%).
It is a quality/cost tradeoff, not a uniform class improvement. The small
fixed cost grid also leaves large unused budgets in some low-cap configurations.

The frozen deployment packet already retains every selected configuration.
Next validation of transfer can replay those unchanged settings on other
recordings, with no cost/profile tuning there. The old crossing3 material has
already been inspected and must not be called newly blind. A stronger simple
Infra-priority control at the same 271-query cost is not part of this report;
an advantage over that control has not been established.
