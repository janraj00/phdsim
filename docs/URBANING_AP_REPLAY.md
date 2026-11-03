# Portable AP export and common frozen-policy evaluator

Implemented and verified on real exported data on 2026-11-03. Ares job
**21577295** completed the 400-train/200-validation export in 2m01s. Its ZIP
SHA256 matched `ce8893d439d446edf0cb328881a0b31523a138b1eed713b844f68e1da7e557c5`
and the common evaluator replayed the unchanged validation choices locally.
This closes an evaluation-data gap found in the audit; it does not change the
audited linear regional policy or establish a new method result.

## Completed development-validation measurement

All rows below use the same 200 crossing2 validation frames and frozen choices.
Primary mAP is four-class global-confidence-sort BEV AP at IoU .5. These are
not full crossing3 results or independently held-out evidence.

| Policy | Primary mAP@.5 | Requests | Saved vs ALWAYS |
|---|---:|---:|---:|
| ALWAYS | 37.6015% | 334 | 0% |
| Audited regional prototype | 37.5371% | 329 | 1.50% |
| Prior ridge / Gain–Geometry | 36.9347% | 296 | 11.38% |
| Prior tree | 37.2465% | 313 | 6.29% |

| Policy | Policy mAP | Same-budget random mean | Same-schedule random mean |
|---|---:|---:|---:|
| Regional | 37.5371% | 37.3700% | 37.5503% |
| Ridge | 36.9347% | 35.8588% | 37.1092% |
| Tree | 37.2465% | 36.6280% | 37.0627% |

Each random mean uses 100 seeds at its reference policy's exact request budget.
The regional prototype has lower mean mAP than schedule random despite higher
F1. This illustrates why F1 cannot replace the declared AP endpoint. Its .06448pp
mAP loss versus ALWAYS accompanies only five saved requests. The spatial
pooling limitation remains; no model, threshold or budget was tuned during replay.
Prior ridge/tree class AP reproduced exactly in both orders. A detailed Polish
summary, per-class results and all controls are in `urbaning-common-ap-21577295.zip`.

Default-order mAP is separately 27.4893% for ALWAYS, 27.4813% for regional,
27.0681% for ridge and 27.1902% for tree. Do not mix those values with the tables.

## Fixed metric contract

- Primary: four-class **BEV mAP@IoU .5 with global confidence sorting**.
- Separately report the pinned upstream default frame-order AP; never mix the
  two orderings or describe their difference as detector/policy improvement.
- Include per-class AP at IoU .3/.5/.7 and common all-source GT counts.
- F1 is a secondary mean-frame micro-F1 diagnostic. Historical F1 utility at
  cost .05 is retained solely to reproduce old results, not for model selection.
- Requests count selected peers once per frame; they are not measured bytes,
  latency, energy or ROI queries. Missing peers use canonical feasible actions.
- Aggregate detections across all included sequences before computing AP;
  never average sequence APs or substitute F1/count deltas for AP.
- The evaluator consumes **already frozen frame choices**. It performs no
  fitting, threshold/feature/budget search or selection of a winning policy.

## Portable archive

The Ares exporter reads existing completed caches for:

- Train: `20241126_0017_crossing1_00` and `20241126_0001_crossing2_00` (400 frames).
- Validation: `20241126_0004_crossing2_00` (200 frames).

Headers reject crossing3 and original-recording overlap before loading cache
payloads. The existing reader verifies GT fingerprints, action fallback aliases,
frozen detector identity and all four baseline class APs against original run
metrics (tolerance 1e-7). Existing files, weights and environments are preserved.
No upstream import, detector inference, package installation or data download
is required; NumPy suffices for the worker.

`urbaning-ap-export.zip` contains `manifest.json`, README and two offline JSONL
files. Each frame stores public source IDs, native association, immutable source
payload/GT fingerprints and class/action/IoU arrays of detection confidence,
TP/FP flags and GT counts. These are **offline outcomes**, not model features.
Manifest bindings preserve the frame-to-prediction mapping and record source
run/trace/payload/code hashes, recording groups, runtime and baseline results
for both AP orders. Class support and confidence arrays must be identical across
IoU thresholds; all actions must use the same GT support. Unavailable duplicate
actions are not exported as additional training/evaluation examples.

The exporter verifies the final ZIP, re-reads it and reproduces all baselines
before printing DONE. `export-completed.json` and stdout record its final SHA256
and byte size, allowing the downloaded copy to be checked. The loader refuses changed file hashes, frame identities,
action masks, malformed detection statistics or failed AP parity. Classes with
no GT yield undefined four-class mAP, rather than being silently dropped or
imputed as zero.

## Ares command

From the AP-replay checkout root, using the existing verified container wrapper:

```bash
sbatch -A plgkgacq-cpu scripts/slurm/urbaning_ap_export.sbatch
```

This submits one 4-CPU, 8GB job with a one-hour **limit**, not a runtime estimate.
It reads the three original caches and writes a new job-specific directory:

`$WORK/phdsim/runs/urbaning-ap-export-JOB_ID/urbaning-ap-export.zip`

Logs are `urbaning-ap-export-JOB_ID.out/.err` in the submission checkout. No
completed cache is reused as a writable output, and partial output is preserved
on failure. `URBANING_AP_OUTPUT` can explicitly override the new output path.

After completion, download into the agreed Mac results layout:

```bash
AP_JOB=YOUR_JOB_ID
mkdir -p "$HOME/Documents/phdsim-results/urbaning-ap-export-$AP_JOB"
scp "plgrajczykjan@ares.cyfronet.pl:/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work/phdsim/runs/urbaning-ap-export-$AP_JOB/urbaning-ap-export.zip" \
  "$HOME/Documents/phdsim-results/urbaning-ap-export-$AP_JOB/"
```

The resulting ZIP is enough for local AP replay; raw point clouds and detector
weights do not need to be transferred.

## Replay the frozen historical policies

Once the real export is available locally, reuse the already supplied regional
policy and prior tree-pilot ZIPs:

```bash
OPENBLAS_NUM_THREADS=4 python scripts/urbaning_ap_replay.py evaluate \
  --archive /path/urbaning-ap-export.zip \
  --choices /path/urbaning-regional-policy.zip \
  --prior-pilot /path/urbaning-tree-pilot.zip \
  --output-dir /new/common-ap-report
```

This reports Car1, Car1+Car2, Car1+Infra, ALWAYS, the frozen audited regional
prototype, and the prior ridge/tree if supplied. It checks exact source-cache
provenance and frame coverage. The old ridge/tree must reproduce their saved
requests, F1 **and both AP ordering modes**. The regional prototype must retain
its previously frozen requests/F1; its newly computed AP is not a repaired
spatial model or an independently evaluated result.

Each supplied acquisition policy receives 100 exact-budget and 100 exact-schedule
random controls, with both AP orderings labeled. Budgets/histograms are checked
explicitly. No independent-p=.5 random is mixed into the main comparison.
The result ZIP includes a readable table and detailed JSON with per-class AP,
request savings, both ordering modes, controls and source hashes.

Future policies can supply a JSON file with schema
`phdsim-urbaning-frozen-choices-v1`, a non-baseline `name`, `split`, exact source
`provenance` (`detector`, `inputs`) and complete `choices` keyed by native frame
identity. Optional `expected_metrics` bind frozen requests and mean frame F1.
Choices must be feasible; the evaluator does not invent fallbacks or infer
choices from labels. Generic provenance is verified against the export before
any new-policy result is accepted.

## Validation and remaining boundary

Locally verified: export/readback and old evaluator parity on nontrivial known
fixtures; an example where global/default-order AP differ despite unchanged F1;
source/split/hash guards; undefined-class behavior; both matched controls; prior
policy adapters; worker shell syntax. Five supplied real-data inspection cases
(20 action outcomes) reproduced their earlier per-class TP/FP/GT and frame F1.
These GT-selected cases do **not** replace the full 600-frame export/parity check.

The existing development recordings were repeatedly inspected. This step repairs
measurement completeness only. A corrected spatial learner and a genuinely new
evaluation split remain separate later tasks; neither is trained or selected by
this entry point. See the [audit](URBANING_AUDIT_2026-11-03.md).
