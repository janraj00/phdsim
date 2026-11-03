# Whole-frame replay of regional predictions

This continues the regional feature ablation with acquisition decisions. It
uses the previously selected 46-feature predictor unchanged. Each action's
signed predicted FP+FN reduction is summed over all 401 cells and four classes.
The whole-frame subset maximizes that sum minus a penalty per requested peer.
Both uses its directly supervised head, not the sum of single heads. Negative
values are retained; overflow is included. No regional outcome mixing occurs.

The fixed count-penalty grid is `0,1,2,4,8,16,32,64`. This penalty is in predicted
error counts and is **not** equated to the existing .05 cost in F1 units.
Validation selects the candidate maximizing mean frame F1 minus .05 times mean
requests. Ties prefer fewer requests, then grid order. This additional selection
uses the already-inspected validation recording, not an unseen test. The full
grid is reported; it must not be presented as an independent performance gain.

## Verified local result, 2026-11-03

The 200 validation frames have Car2 available throughout and Infra in 134;
ALWAYS therefore makes 334 requests. The selected count penalty is 8.

| Policy | Mean frame F1 | Requests | Saved vs ALWAYS |
|---|---:|---:|---:|
| ALWAYS | 67.4533% | 334 | 0% |
| Regional, selected | 67.3785% | 329 | 1.50% |
| Previous ridge | 66.8805% | 296 | 11.38% |
| Previous tree | 67.0080% | 313 | 6.29% |
| Regional, penalty 16 (unselected tradeoff) | 62.9455% | 168 | 49.70% |

The selected policy removes Car2 in five both-available frames and keeps Infra.
It never deliberately chooses no query here. F1 decreases .07476 percentage
points from ALWAYS, while mean utility rises only .0005024. This is a small
development tradeoff, not a large acquisition improvement. Regression-error
improvement in the previous experiment did not imply comparable query savings.
Prior ridge/tree metrics are independently reconstructed from counts and their
saved choices after exact validation payload/trace/detector provenance checks.

## Two random questions, same 329-request budget

Both controls use seeds 0–99 and the same public availability. No target quality
is used to generate their choices. They are retrospective controls matched to
the policy schedule, not independently deployable policies.

- **Budget:** shuffle the policy's 0/1/2-request counts within feasible-action
  strata, then randomize partner identity. Tests timing plus source choice.
  Preserves total requests and the 0/1/2 histogram within each stratum exactly.
- **Schedule:** retain the number of requests on each exact frame, randomize
  only partner identity. Tests source choice at the policy's selected times.

Budget-control mean F1 is 67.2597% (range 66.9490–67.4171%); the regional policy
exceeds 92 of 100 draws. Schedule-control mean is 67.1036% (range
66.7985–67.3785%). The latter has only 32 possible source-choice schedules because
only five frames choose one of two partners; the 100 seeds produced 30 unique
schedules. These randomization ranges are not confidence intervals over
recordings, and the validation-selected policy has an optimistic comparison.

## Reproduce and interpret

```bash
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4 \
python scripts/urbaning_regional_policy.py \
  --dataset /path/urbaning-regional-dataset.zip \
  --model /path/regional-learning/models/full.json \
  --prior-pilot /path/urbaning-tree-pilot.zip \
  --output-dir /new/regional-policy-output
```

NumPy and Matplotlib suffice; no detector, package installation, training or
crossing3 access occurs. The ZIP preserves the selected model and penalty,
per-frame choices, complete candidate results, random controls and tradeoff
figure. Original files and reports are retained.

**mAP is not computed:** exported counts do not contain all detection
confidences/TP flags. The report marks it unavailable rather than deriving it
from F1 or copying an old policy's AP. A later AP replay must verify the original
cached predictions against `validation_provenance`, replay these frozen choices
and report AP ordering explicitly. Previously computed AP, when included for an
old policy, is labeled as such. Simulated peer/frame counts do not measure bytes,
latency, network traffic or sensor energy.
