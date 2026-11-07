# Frozen final-model TRAIN/validation diagnosis

Status2026-11-07: prepared and locally checked; no native diagnostic job submitted
from this session. Source controlled run is
`urbaning-cobevt-rgb-controlled-001` at scientific code `fffb0df9`.

## Why this diagnostic

User-reported validation200 for seeds0/1: original LiDAR21.6500% each;
LiDAR adapter18.1889%/19.4775%; RGB adapter17.4971%/18.7434%; shuffled-training
control18.7901%/18.3470%; shuffled-evaluation RGB15.1754%/16.4852% BEV mAP@.5.
The third seed/full source archive has not been reviewed here. These two seeds
show a negative development result, not an RGB gain. TRAIN8 memorization cannot
explain why the400-frame-trained models lose validation AP.

Evaluate the **unchanged final models** on their400 TRAIN frames and compare
with their already-computed200-frame validation results. This is post-hoc
diagnosis, not new fitting, checkpoint selection, parameter tuning or a blind
test. Retain the same four-class global-confidence-sort BEV VOC mAP@IoU.5;
also keep class AP, IoU.3/.7 and the upstream frame-order mode. No F1 replacement.

## Inputs and immutability

Require the completed original collector archive and checksum receipt. Bind
protocol, inventory, TRAIN-only normalizers, seed reports, freeze receipts,
all used final model files and extraction receipts to their canonical bytes
in that archive. Check the original scientific source hashes, model bundle,
thread count,32-epoch recipe, complete final-epoch histories, seed/mode identities,
normalizer/train-key bindings and feature-manifest hashes.

Use a separate non-nested output directory and detached checkout. Do not call
the original protocol writer or loaders with the source output as destination.
Loading original TRAIN provenance writes its temporary portable packet only
under the new diagnostic output. Source cached arrays and per-frame manifests
are read and verified; no source output/model/normalizer is rewritten. Compare
source file hashes again after each worker and during collection.

No RGB images, image encoder, LiDAR backbone, target regeneration, optimizer or
backward pass. Load frozen adapters and original heads, read existing BEV/RGB
and TRAIN anchor targets, then run only residual adapter, detection heads,
unchanged decoder and offline matching/loss evaluation. All parameters are
`eval()` and `requires_grad=False`, inference uses `no_grad`. The direct launcher
sets the process hash seed BEFORE imports and needs no private torchvision
bootstrap/install. It never writes to the original dependency directory.

## Conditions

| TRAIN evaluation | Model/input | Validation comparison |
|---|---|---|
| Original LiDAR | Frozen official heads, original cached Car1 BEV | Original cached validation report |
| LiDAR adapter | Final LiDAR adapter; RGB/count channels zero | Same final model and condition |
| RGB adapter | Final aligned-trained RGB adapter; aligned RGB | Same final model and condition |
| Shuffled-training control, aligned | Final shuffled-trained model; aligned TRAIN RGB | Matches aligned validation input condition |
| Shuffled-training control, as trained | Same final shuffled-trained model; original far-shuffled TRAIN RGB | N/A: no matching original validation condition |

The last row is a separate in-sample diagnostic. Do not interpret its gap to
aligned validation as a pure generalization gap: input alignment also changes.
The original shuffled-evaluation validation diagnostic is retained in the
source metrics but is not confused with this shuffled-training row.

Original TRAIN LiDAR is seed-independent and is evaluated once, by worker0.
Four learned-model/input conditions are evaluated for each of3 seeds:
**400 +4x400x3=5200 head/decoder frame evaluations**. All new work uses existing
features. Validation inference and its earlier complete raw-prediction replay
are not repeated: validation metrics are copied only from the checksum-bound,
independently replayed completed original reports.

## Reporting and interpretation

Report TRAIN400 and validation200 mAP **with change relative to the original
LiDAR on the SAME split**. Raw TRAIN/validation AP can differ simply because
recordings, object populations and difficulty differ. Also report both original
TRAIN recordings separately, per-class AP, each seed and paired RGB-minus-LiDAR-
adapter changes for TRAIN and validation. Mean over seeds averages AP values,
not pooled predictions or an ensemble; seed variability is not recording-level
uncertainty.

Measure frozen-model TRAIN detection/classification/regression loss from existing
anchor targets, with residual regularization separately. Preserve original epoch
training histories. A fixed final-model loss over the full TRAIN split differs
from an epoch mean collected WHILE parameters changed; neither is AP.

Improved TRAIN change but worse validation change supports a generalization
gap, with overfitting/domain differences among possible causes. If both TRAIN
and validation AP lose despite lower detection loss, inspect objective/metric
alignment and detection behavior rather than assuming a generalization-only
problem. This diagnostic alone does not identify a unique cause or disprove
multimodal perception.

Per-frame raw prediction/GT exports have model/normalizer/protocol/donor bindings
and checksums. Partial evaluation resumes completed frames without repeating
their head inference. Collector independently recomputes TRAIN AP in both modes,
including per-recording AP, from every raw NPZ before creating its final report.
It also checks identical TRAIN frame/GT bindings across all models/seeds and
loss aggregation against the saved frame receipts.

## Ares launch

From the new detached diagnostic checkout:

```bash
bash scripts/slurm/submit_urbaning_cobevt_rgb_train_eval.sh
```

Source defaults to `phdsim/runs/urbaning-cobevt-rgb-controlled-001`.
Output defaults to `phdsim/runs/urbaning-cobevt-rgb-train-eval-001`, with its own
`logs/`. If the completed source exists, submit immediately. Otherwise attach
`afterok:21599633` only if that original collector is still active; fail clearly
if the source is incomplete and the collector has already left the queue.
The third submitter argument can identify a different original collector.

Creates TRAIN EVAL ARRAY0–2%2 plus a dependent REPORT task. Each worker uses
8CPU/24GiB/8h ceiling; collector8CPU/24GiB/4h ceiling. These limits are not ETAs.
Stage/seed locks prevent concurrent writers; protocol initialization has a short
cross-worker file lock. Original models/features remain usable by other readers.

Return `urbaning-cobevt-rgb-train-eval.zip`: compact mean table, detailed per-seed/
recording/class AP, source hashes and validation results, original training
curves, frozen TRAIN losses and all raw TRAIN predictions/GT. Large feature
caches and original model weights are referenced, not copied into the new ZIP.

## Local checks

Six new tests cover complete three-seed frozen evaluation/export/replay/reuse;
real nonzero saved state loading rather than zero initialization; separate
as-trained shuffle condition; once-only original TRAIN baseline; exact source
content preservation; guards forbidding optimizer/fitting/CNN/backbone calls;
mid-evaluation resume without repeated head inference; changed prediction/model/
cache/source-archive and nonfinal recipe rejection; concurrent protocol creation;
and fake-Slurm waiting/ready/failed-source cases. Synthetic predictions test the
wiring and are not a research result. Source compatibility/CLI and Python/shell
checks also run locally; native400-frame evaluation remains pending on Ares.
