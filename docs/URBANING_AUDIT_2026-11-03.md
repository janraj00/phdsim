# UrbanIng audit — 2026-11-03

## Verdict and evidence boundary

The completed CoBEVT reference, frozen counterfactual caches and recording-based
input/target exports remain useful. The current results do **not** establish an
acquisition advantage over matched-budget random. The newest linear regional
predictor followed by sum aggregation loses the spatial binding needed for its
intended acquisition interpretation; it remains a development prototype.

This audit checked the latest six shared ZIPs, original benchmark/model hashes,
reported metric arithmetic, 1400 frame choices and random schedules, the full
600-frame regional input/target contract, five frozen regional models, and
all 200 validation random-control replays. Five real-data feature matrices were
recomputed exactly from Car1-only evidence and assumed shared poses. No detector
inference, fitting, raw download or Ares job was performed. The full 1400 raw
prediction caches and detector runtime are on Ares; their matching/AP were not
independently recomputed here. Report consistency is not raw-data revalidation.

## Findings

### High: the regional acquisition path discards the spatial association

The regional predictor is affine in each cell's features. Summing predictions
over cells/classes gives an affine function of **sums of input features**:

`sum_cell,class prediction = constant + effective_weights @ sum_cell features`.

It therefore cannot generally bind low confidence in a particular cell to
proximity/view geometry of a particular partner through the current additive
features. Separate regional maps do not establish a spatially aware final
decision. Directly supervised joint heads avoid assuming additivity of partners,
but do not repair this spatial pooling limitation.

The audit constructs two same-class Car1 boxes at x=-30,+30m, with Car2 at -50m
and Infra's proxy at +50m. Exchanging confidence .2/.9 changes which partner is
near the low-score box. Real feature generation yields exactly equal column sums.
The frozen model's local maps change by up to .573233, while summed action scores
change only 1.33e-15. All eight penalty-grid decisions remain identical. This is
a concrete structural counterexample, not an assertion that every pose change
has no effect. Nonlinear distance features can still encode global pose biases.

Do not present this implementation as demonstrated need-to-partner spatial
reasoning. No method was retuned during the audit to obtain a better number.

### High: intermediate metrics were overinterpreted and endpoints changed

The 23.4% figure is a relative decrease in **regional prediction MSE versus
predicting zero**, from .049041 to .037557. It is not F1, mAP, object recovery,
query saving or an independent performance estimate. Harm-cell MSE worsens
1.278871→1.602021. Car1-empty-region improvements are tiny or absent.

The global policies predict frame-F1 gain and select F1-minus-request-cost.
The regional model predicts FP+FN count reduction, selects ridge alpha by MSE,
then chooses an error-count penalty by validation F1-minus-cost. Such surrogates
are not intrinsically invalid, but the chain requires justification and final
evaluation against the declared task endpoint. It cannot substitute for mAP.
The .05 F1 utility cost is not equal to 8 predicted errors per query.

Promising a new-policy mAP comparison before confirming the necessary exported
scores was an execution/reporting error. Counts cannot recover AP: the audit
shows identical TP/FP/FN and F1=2/3 with Vehicle AP near 1 or .5 after changing
only detection confidence order.

### High: validation-selected development was confused with generalization

Policy development uses 400 training frames from two original recording groups
and 200 validation frames from one other group. All 401 regions are retained;
160,400 training cell rows do not create 160,400 independent observations.
The inspected validation recording selected regularization, feature profile and
the later request penalty. Comparisons on it are development-only and optimistic.

The 1400-frame crossing3 report covers seven sequences but five original
recordings. A crossing3 pilot was inspected before subsequent method extensions.
The original frozen-policy numbers remain reportable with that qualification;
new methods must not call all previously examined crossing3 material pristine
unseen evidence. No train/validation recording overlap was found in the exports.

### High: old full-test policies do not beat exact-budget random

All rows below are the same 1400 crossing3 frames; mAP is global-confidence-sort
BEV mAP@.5 over four classes. Random rows use 100 draws, not 100 new datasets.

| Policy/control | mAP@.5 | Mean frame F1 | Requests | Saved vs ALWAYS |
|---|---:|---:|---:|---:|
| ALWAYS | 33.7102% | 54.5905% | 2033 | 0% |
| Gain–Ego | 33.1274% | 53.7529% | 1838 | 9.59% |
| Random, Ego budget mean | 33.1641% | 53.8918% | 1838 | 9.59% |
| Gain–Geometry | 32.2393% | 52.2992% | 1533 | 24.59% |
| Random, Geometry budget mean | 32.3247% | 52.8171% | 1533 | 24.59% |

Each learned policy loses F1/utility to all 100 budget-matched draws. For mAP,
Ego exceeds 34/100 and Geometry 18/100 draws, while both remain below the random
mean. Do not conflate the F1 result with a claim of losing mAP to every draw.
The hindsight GT-assisted reference is a privileged F1-cost reference, not a
deployable policy or an mAP oracle.

### Medium: AP ordering changes the reported value materially

The pinned upstream CLI defaults to `global_sort_detections=False`. Our early
smoke evaluator uses True. The full benchmark and full-policy report contain
**both**, generated from the same detections. ALWAYS mAP@.5 is 24.8134% with
upstream default ordering and 33.7102% with global sorting. That difference is
not a better detector or a policy gain.

The released checkpoint's `eval_3d_det.yaml` averages to 24.8563%; our default
reference is lower by .04288 percentage points. Largest class difference at
IoU .5 is .19884pp. This is close checkpoint-result reproduction, not an exact
paper-table certification. CPU/software/preprocessing equivalence was not
re-established from raw inputs in this audit. The independent AP integration
was checked against the pinned upstream functions on 480 synthetic comparisons
across both orderings, agreeing within 1e-12; raw box matching remains a separate
check. Aggregation code merges detections before AP, rather than averaging
sequence APs.

### Medium: the regional replay has only a small selected tradeoff

On 200 crossing2 validation frames, ALWAYS has F1 67.4533% and 334 requests;
regional has F1 67.3785% and 329 requests. The five saved requests are 1.50%,
with .07476pp F1 loss. It retains Infra and skips Car2 on five frames, and never
selects NO when a peer is available. Penalty 16 saves 49.70% but F1 falls to
62.9455%; it was not selected by the predefined validation utility.

The prior ridge has F1 66.8805% at 296 requests; its coefficient/scaling arrays
equal the existing Gain–Geometry model exactly. A successful validation pilot
is not a new independent model success. Its later full-test result is above.

### Medium: random controls are valid for their stated questions, not universal

The generator does not read GT or outcome quality. Both controls preserve the
exact 0/1/2 pull histogram and total within receiver/feasible-action strata.
Budget matching shuffles counts between eligible frames then randomizes identity;
schedule matching fixes the number on each frame and randomizes only identity.
Full-test budget matching is not additionally stratified by original recording.

For the selected regional policy, budget random averages 67.2597% F1 at the
same 329 requests. Schedule random averages 67.1036%. Only five frames request
one of two available peers; schedule random has 32 possible schedules and 30
unique schedules among 100 seeds. "92/100 draws beaten" is a randomization
description on selected validation, not statistical significance or 92% success
probability. Independent p=.5 random has a different budget and is secondary.

### Medium: a delivered ZIP was damaged

Five of six shared ZIPs passed central-directory/CRC checks. The regional
learning ZIP was incomplete/damaged at `validation-predictions.npz`. The cause
is not established. Nine complete members (all five models, report, README,
SOURCE and PNG) were recovered using local headers and CRCs, and all five model
files matched the existing local bytes. Their validation MSE and the selected
policy were reproduced from the verified dataset without fitting. A compact
replacement preserves those nine members unchanged, adds an audit repair note
and omits the incomplete prediction NPZ. These predictions can be regenerated
cheaply from the frozen models. Preserve the original as version history.

## What survives, what remains missing

- Preserve the frozen checkpoint, conversions, raw per-action prediction caches,
  GT identities, source associations, pose sidecars, reports and their hashes.
- The inspected code keeps GT/peer perception out of the policy feature/prediction
  interfaces; five real feature matrices reproduced exactly from Car1 evidence.
  This is not a certification of causal online metadata or all raw annotations.
- One released LiDAR CoBEVT checkpoint was studied. The checked v1.0.0 release
  has only one model archive plus annotation assets. This is not the requested
  every-fusion-method comparison, nor an RGB/thermal experiment.
- Car1-only means that cooperative model with peer inputs removed, not the
  authors' separately trained No Fusion baseline. Infra is a site bundle/origin
  proxy, not a known physical pole or visibility/FOV estimate.
- Requests are offline peer/frame counts, not measured transmitted bytes,
  latency, energy or computational savings. The equal .05 charge is a proxy.
- New regional-policy mAP needs confidences/classes and TP/FP flags per detection,
  or the original cached boxes/scores/GT plus the existing matcher. Those caches
  already exist on Ares. This is an export/replay gap, not a reason to repeat
  multi-hour detector inference. The numerical full-test AP in existing reports
  is available; it is the new regional policy's AP that is missing.
- Before any new experiment, fix and record the endpoint/order, budget range,
  development/evaluation groups and controls. This audit changes no frozen
  detector, policy coefficients, historical numbers or test selection.

## Reproduce the audit

```bash
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4 \
python scripts/audit_urbaning_results.py \
  --artifacts /path/to/original-six-shared-zips \
  --benchmark /path/benchmark-report.json \
  --geometry-model /path/geometry-gain.json \
  --regional-model-dir /path/original-regional-learning/models \
  --output-dir /new/audit-output
```

Keep the pre-repair learning ZIP for reproducing the artifact-recovery check.
The checker is read-only toward its inputs. Audit JSON records exact input hashes
and structural evidence. Passing the earlier software tests did not establish
scientific validity; the new audit includes the missing spatial counterexample.

Primary references: [pinned evaluator](https://github.com/thi-ad/UrbanIng-V2X/blob/d5766e75f985c6c566a09abfa23d3fbb32f03820/opencood/opencood/utils/eval_utils.py),
[pinned inference defaults](https://github.com/thi-ad/UrbanIng-V2X/blob/d5766e75f985c6c566a09abfa23d3fbb32f03820/opencood/opencood/tools/inference.py),
[checked v1.0.0 release](https://github.com/thi-ad/UrbanIng-V2X/releases/tag/v1.0.0).
