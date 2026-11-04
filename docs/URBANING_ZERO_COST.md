# Zero-cost policy: exact-total random, classes and recordings

Status: **prepared, not a completed100-seed experiment** (2026-11-04).
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
