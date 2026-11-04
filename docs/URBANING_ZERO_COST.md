# Zero-cost policy: exact-total random, classes and recordings

Status: **Ares job21587032 completed and checked** (2026-11-04).
The user authorized an Ares job after the explicit cost0 diagnostic on the same
1400 crossing3 frames yielded33.6741% global-sort BEV mAP@.5 at1813 queries,
versus ALWAYS33.7102%/2033. This point was inspected before this follow-up and
is **post-hoc**, not a new validation-selected or blind-test configuration.

## Frozen diagnostic

Use only the existing geometry gap/benefit score NPZs from job21586593 and
portable detection statistics from job21578375. Keep all model predictions,
the same10 gap-selected cells among400 and the direct joint-benefit head.
Change the error-count cost from.5 to0 only. No cost search, model fitting,
forest inference, detector, raw data downloads, packages or environment edits.

Before evaluating controls, reproduce the original cost.5 choices and historical
policy AP in both ordering modes. Verify exact original ZIP/member hashes,
checkpoint score hashes, shapes and detector/frame/payload provenance. Refuse
a different zero-cost total than the previously observed1813. The protocol is
saved before reading the fixed crossing3 inputs.

Two controls at **exactly1813 total queries**, seeds0–99:

1. Uniform random sampling without replacement over all feasible frame/peer
   query events. Receives only the scalar total; zero/one/both naturally arise.
2. Strong secondary reference: query Infra when available, otherwise Car2; add
   random Car2 queries on both-available frames until total1813. This starts
   with1311 requests and adds502 of722 possible extra Car2 requests. It does
   not receive the model's timing, choices, confidence or GT.

The second control checks whether learned selection adds value beyond Infra
priority. Both controls borrow an exact observed cost retrospectively and are
not claimed as online policies. The prior pure independent p=.25/.5/.75/.9
curves remain visible from the previous verified report.

## Report

Primary metric stays global-confidence-sort four-class BEV mAP@.5, requests,
savings and mAP loss versus ALWAYS. Default-order AP is reported separately;
F1 is diagnostic only. Report full and class AP for the zero-cost policy,
original cost.5, ALWAYS and older policies. Include both randomized controls'
100 per-seed results and class-AP mean/range/std.

Evaluate separately for all seven200-frame sequences and **five original
recording groups**. Sibling clips0010_08/09 and0024_08/09 share their groups.
Group AP is computed from pooled detection statistics with the same evaluator,
not from averaging sequence AP. Global1813 totals match, but per-group totals
can differ; show those costs rather than claiming equal subgroup expenditure.
Random seed spread does not establish uncertainty across independent recordings.
Small overall mAP loss does not prove equivalence or uniform class performance.

Checkpoint caches include scope frame keys and separate scope names so identical
action vectors on different recordings cannot collide. Atomic per-action/seed
checkpoints support resume at the same commit/inputs/output directory. Preserve
the earlier frozen model/defaults and all source runs.

## Submit on Ares — no new upload

Existing inputs, verified by the worker:

- `phdsim/runs/urbaning-gap-full-21586593/urbaning-gap-full.zip`, SHA256
  `82227530fb755da55bc516cc495ebeb70aaa9323a3e6adf892b13af3ee814869`.
- `phdsim/runs/urbaning-frozen-full-21578375/urbaning-frozen-full.zip`, SHA256
  `e7070e7bfc4743a7bba90310ce3a39ba893281c62c6f7c0e2a05c6c56472e802`.

Fetch `codex/urbaning-zero-cost`, create a fresh worktree at the reviewed commit,
then submit from that root:

```bash
sbatch -A plgkgacq-cpu scripts/slurm/urbaning_zero_cost.sbatch
```

Resources:4CPUs/12GB/2h upper limit, not a runtime estimate. Uses the established
container Python wrapper with NumPy1.26.4. No sklearn/Torch/Open3D required.
Output: `phdsim/runs/urbaning-zero-cost-JOBID/urbaning-zero-cost.zip`, including
protocol, frozen choices, all metrics/controls/group/class outputs and a Polish
summary. To resume, pass the same previous absolute output directory as the
first sbatch-script argument, keeping the same commit. A file lock prevents
concurrent writers.

## Verification

Three focused tests passed: strong-control exact cost, fallback/availability and
random extra selection; grouping sibling sequences correctly; scoped cached AP
measurement without cross-recording collisions. Bash syntax passed. A real-input
two-seed end-to-end smoke run reproduces1813 queries, both controls, class outputs,
seven sequences/five groups, both AP orders, final ZIP hashes and identical resume.
The full100-seed Ares job has not been submitted from this session.

## Completed Ares follow-up — job21587032

Completed in **7m19s**, Slurm exit0. Uploaded output SHA256
`f014f2fa71da358961d90e9f5c4d9459fa9b233a8b3cc26d065fa6b058dfc9a3`,
2,486,881 bytes. ZIP CRC/member hashes and implementation hashes passed.
All10 fixed-policy results reproduced for full1400, seven sequences and five
original recording groups, in both AP modes. Both100-seed control schedules
and global1813-query totals regenerated exactly; summary/class-summary arithmetic
checked across all scopes. AP independently replayed at seeds0/99 for each
control across all scopes and both modes. This is a sampled control-AP check,
not a claim to rerun all100 control AP evaluations locally.

### Global comparison

| Policy | Global-sort mAP@.5 (%) | Queries |
|---|---:|---:|
| ALWAYS | 33.7102 | 2033 |
| Original geometry/top10 cost.5 | 32.6966 | 1448 |
| Same geometry/top10 cost0, post-hoc | **33.6741** | **1813** |
| Uniform exact-total random,100-seed mean | 32.7412 | 1813 |
| Infra-priority/fallback + random Car2 extras,100-seed mean | 33.1509 | 1813 |

Cost0 saves **220 queries (10.82%)** versus ALWAYS at observed mAP loss
**.0361pp**. It exceeds uniform random mean by **.9329pp** and the stronger
Infra-priority mean by **.5232pp** at exactly the same global query total.
It is above all100 draws from each control: uniform range32.5027–33.0615%,
Infra-priority32.9923–33.3003%. This is conditional randomization evidence on
already-inspected recordings, not a recording-level significance test.

Pure independent random p=.9 remains **32.8147% /1829.68 queries**; other
predeclared probabilities are preserved in report.json. Do not replace the
independent random baseline with model-conditioned schedule controls.

### Class AP shows the average hides tradeoffs

| Class | ALWAYS AP@.5 (%) | Cost0 AP@.5 (%) | Difference (pp) |
|---|---:|---:|---:|
| Vehicle | 63.6482 | 63.3980 | -0.2502 |
| Heavy_Vehicle | 33.1881 | 34.0998 | +0.9117 |
| 2Wheeler | 32.5086 | 32.2366 | -0.2721 |
| Pedestrian | 5.4957 | 4.9620 | -0.5337 |

Heavy_Vehicle improves while all three other classes drop. In particular
Pedestrian falls5.4957→4.9620% AP (.5337pp). Near-equal macro mAP does not
establish per-class safety/equivalence or a noninferiority result.

### Five original recording groups

| Recording | Frames | ALWAYS mAP (%) | Cost0 mAP (%) | Difference (pp) | Cost0 / ALWAYS queries |
|---|---:|---:|---:|---:|---:|
| recording/20241127_0009 | 200 | 36.0734 | 37.5254 | +1.4521 | 256 / 370 |
| recording/20241127_0010 | 400 | 41.6217 | 41.5182 | -0.1035 | 515 / 543 |
| recording/20241127_0011 | 200 | 37.7316 | 37.1972 | -0.5344 | 294 / 321 |
| recording/20241127_0012 | 200 | 30.1685 | 30.1685 | +0.0000 | 229 / 229 |
| recording/20241127_0024 | 400 | 26.3831 | 26.2583 | -0.1247 | 519 / 570 |

One recording improves, three drop and one is unchanged versus ALWAYS.
The largest loss is.5344pp in0011;0009 gains1.4521pp while saving114 queries.
Group AP is pooled over that group, not an average of clip AP; overall AP is
not the arithmetic mean of these group values. Against the strong random mean,
cost0 is higher in4/5 groups and lower in0012, but subgroup query budgets differ.
For example0009 uses256 vs random mean317.63 queries;0012 uses229 vs213.09.
Only the total1400-frame1813 budget is exactly matched.

### Interpretation to preserve

This inspected result supports useful partner selection beyond query penalty
and beyond simple Infra priority **on these data**. Cost0 was requested after
viewing full results: no new blind/generalization claim. Keep the original
cost.5/28.78%-saving point separately as the validation-selected tradeoff.
The best model still uses geometry/availability, not current Car1 detections;
no causal visibility/gap map, ROI transmission, byte/latency gain or learned
abstention with available partners is established. No new model or detector
was run, and no original production/default configuration was changed.
