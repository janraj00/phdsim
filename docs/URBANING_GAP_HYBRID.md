# Separate current Car1 gap localization from geometric partner benefit

Status: **Ares job21586927 completed and checked** (2026-11-04). The user asked how
to incorporate current Car1 evidence after the geometry-only full replay.
This is an additional **development-validation** experiment on the original
200 crossing2 frames, not a new full1400 result or an independent blind test.

## Question and fixed comparison

The previous full geometry-only point saves28.78% queries at1.0136pp mAP loss,
but does not use current Car1 detection evidence. The existing homogeneous
combined model already performed worse (32.3681%/1506 vs32.6966%/1448); adding
the same features again is not a new hypothesis.

Instead cross the two existing independently trained stages:

| Gap score selects ten fields | Subset-benefit heads score the same ten | Role |
|---|---|---|
| Geometry | Geometry | Existing reference |
| Current Car1 evidence | Geometry | Primary proposed hybrid |
| Current Car1 evidence | Current Car1 evidence | Existing second reference |
| Geometry | Current Car1 evidence | Reverse-stage control |

Models, source feature definitions, field count and benefit targets are unchanged.
The local profile contains cell coordinates and current Car1 entropy/detection/
neighbor summaries; it does not receive partner poses. The geometry profile has
cell coordinates and partner pose/availability, not current Car1 detection scores.
Local scores are engineered evidence summaries, not calibrated uncertainty or
a physical observability measurement. Ten fields are selected from **all400**;
the study is not restricted to fields without detections.

Every variant sums predicted signed FP+FN reduction from the same ten selected
fields separately for Car2, Infra and the direct joint head. Subtract one cost
per actually requested peer, choose one feasible whole-frame action. No GT enters
the action function. No composition of detector outcomes across cells, no ROI
transmission or per-field communication charge.

## Evaluation and freeze

Primary: compare all four pairs at the **same previously used cost .5**, including
the unchanged geometry reference. This is not an equal-query-count comparison;
actual requests must be reported. Also apply the same previous error-cost grid
0/.25/.5/1/2/4/8/16/32/64, selecting within each pair under validation query caps
.5/1/1.5 per frame using global-sort four-class BEV mAP@.5, then fewer queries,
then grid order. All12 selected points are retained; no cross-pair winner is chosen.
The model parameters are not refitted. These cost selections use an already
inspected development recording and are not independent evaluation.

The two homogeneous controls must exactly reproduce original choices and AP in
both modes at every grid cost. Reuse the same predeclared 100-seed pure independent
random curves. Add uniform fixed-total random controls at all selected/fixed-point
query totals; existing totals are reused after seed0/99 parity, new totals are
replayed at seeds0–99. Fixed-total controls receive no model timing/histogram and
are retrospective diagnostics, not online policies. Random seed spread is not
uncertainty across recordings. Both AP orders/class AP remain in report.json;
F1 is diagnostic only. Query counts do not measure bytes or latency.

Protocol is saved before candidate replay; frozen mixed configurations and original
model JSON bytes are packaged before random controls. Checkpoints bind protocol,
implementation, exact inputs and action lists. No crossing3 archive is referenced
or opened by this job; development dataset/AP readers retain their crossing3 guards.
The hypothesis was proposed after reviewing prior full crossing3 results, so later
replaying a frozen hybrid there would still not create a new blind test.

## Existing Ares inputs — no upload required

The same13MB input packet already exists:
`phdsim-work/inputs/urbaning-gap-acquisition-inputs-001.zip`, SHA256
`c1e72f33bdbd61edab2773bac81d2f582b88ed4d625e9743c35ac194d8bb50ee`.
The original validation reference is
`phdsim/runs/urbaning-gap-acquisition-21586379/urbaning-gap-acquisition-validation.zip`,
SHA256 `78c2e20d12acb3334931d0ca763e0cf4d414f2ba7779ef0c67e95869416e8786`.
The wrapper verifies these existing files; missing inputs fail without downloads,
training, detector calls, package installs or shared venv changes.

Fetch `codex/urbaning-gap-hybrid`, create a fresh worktree at the reviewed commit,
and submit from that root:

```bash
sbatch -A plgkgacq-cpu scripts/slurm/urbaning_gap_hybrid.sbatch
```

The established container Python wrapper needs NumPy1.26.4 only; sklearn/Torch/
Open3D are not needed. Resources:4CPUs,12GB,2h upper limit, not a runtime estimate.
Default output: `phdsim/runs/urbaning-gap-hybrid-JOBID/`. The result
`urbaning-gap-hybrid-validation.zip` includes all40 candidate metrics/choices,
the four common-cost points,12 cost-selected points, class AP/both orders, pure
random and fixed-total controls, `WYNIKI_PL.md` and `frozen-hybrid-inputs.zip`.
Resume by passing the previous output directory as the first sbatch-script
argument, keeping the same commit and inputs. A lock rejects concurrent writers.

## Validation before submission

Three focused tests check that swapping only the gap scores changes selected
fields and the partner while the benefit heads remain fixed, GT cannot be passed
through the public function, selection obeys mAP/query caps rather than F1, and
only the exact development reference is accepted. All16 gap-related tests and
bash syntax passed. A real-input, reduced-grid/two-seed smoke test exercises all
four stage combinations, homogeneous parity, report/deployment ZIP hashes and
identical resume. The full fixed protocol remains an unrun Ares experiment.

## Completed Ares validation — job21586927

Completed in50s, Slurm exit0. Uploaded result SHA256
`f7ea1bdce81ac9a98df07367c2b60fb3e107b171e693be5daaa667461b4a7677`,
2,426,684 bytes. ZIP CRC/member hashes, original model bytes, deployment SHA
and implementation hashes passed. All40 candidate AP outcomes reproduced in
both orders, all8000 action decisions reproduced from the frozen public scores,
and all12 budget selections reproduce the declared rule. Secondary controls
checked independently at seeds0/99 in both AP modes. No new fitting/detector
or crossing3 access. This remains the same200-frame development validation.

### Common unchanged cost .5

| Gap localization | Partner-benefit scoring | mAP (%) | Queries |
|---|---|---:|---:|
| geometry | geometry | 36.0361 | 271 |
| local | local | 37.6039 | 333 |
| local | geometry | 32.1397 | 242 |
| geometry | local | 32.4011 | 234 |

### Cost-selected points under the300-query validation cap

| Gap localization | Partner-benefit scoring | Error cost | mAP (%) | Queries | Same-total random mean mAP (%) |
|---|---|---:|---:|---:|---:|
| geometry | geometry | 0.5 | 36.0361 | 271 | 34.8337 |
| local | local | 2 | 35.4918 | 283 | 35.4288 |
| local | geometry | 0.25 | 34.1327 | 288 | 35.6541 |
| geometry | local | 0.25 | 34.7960 | 277 | 35.1287 |

### Interpretation

The proposed local-gap/geometric-benefit composition **did not improve the
validation tradeoff**. Even after selecting its cost within the original grid,
it yields34.1327% at288 queries, versus36.0361% at271 for geometry/geometry:
**1.9035pp lower mAP and17 additional queries**. The reverse pairing is also
dominated at this cap:34.7960%/277. Both mixed selected points are below their
secondary exact-total random means (35.6541% and35.1287%, respectively).
At unchanged cost.5, the proposed hybrid gets32.1397%/242, also below its
same-total random mean33.4925%. Different query counts at common cost prevent
calling the mAP difference alone a controlled quality loss at equal expenditure.

Local/local at cost.5 is practically ALWAYS:37.6039%/333 versus37.6015%/334.
The .0024pp advantage with one saved query is not a substantial acquisition
gain. Under cap300 its selected point remains35.4918%/283, as previously.

Ranking more fields that contain Car1 misses does not by itself establish that
a specific partner can recover those misses or improve global AP. This is a
reason to investigate supervision/compatibility, not a demonstrated causal
explanation of the hybrid result. A proposed future target could distinguish
partner-recoverable gaps from all misses; no new target/model has been trained.
Do not present this failed composition as evidence that current Car1 evidence
is universally useless. No hybrid crossing3 run has been performed or proposed
as an automatic next job; preserve the earlier full geometry result separately.
