# Experiment status and next steps

## Current experiment: own PSTNet RGB training

The five-class RGB pilot uses the authors' RGB architecture and preprocessing,
an ImageNet-initialized ResNet18 encoder, a random decoder, and full-network
fine-tuning. Optimizer settings are our choices; this is an own training run.

| Item | Pilot value |
|---|---|
| Input | 640 x 360 RGB, values divided by 255 |
| Training | 48 frames from 11 recording families |
| Validation | 24 frames from `bag1`, `bag7`, `bag11` |
| Epochs | 5; epoch 5 selected by global validation mIoU |
| Training mIoU | 52.36% |
| Validation mIoU | 31.21% |
| Validation, background-only prediction | 19.24% |
| Validation foreground mean IoU | 15.07% |

| Class | Validation IoU |
|---|---:|
| Background | 95.74% |
| Fire extinguisher | 19.54% |
| Backpack | 22.49% |
| Hand drill | 0.00% |
| Survivor | 18.25% |

The network starts localizing some objects, but predictions still confuse classes
and contain false positives. The train/validation gap is substantial. Weighted
validation cross-entropy increased from 1.5997 to 2.2310 despite the improved masks.
This pilot does not establish reliable uncertainty estimates or strong segmentation.

The 288 official test frames were not used in this pilot. Six separate training
families (`bag4`, `bag5`, `bag6`, `bag8`, `bag12`, `bag17`; 194 frames) were reserved
for future acquisition learning. The remaining vision-training pool contains
273 frames, of which the pilot used 48; the validation families contain 130, of
which the pilot used 24.

Local artifacts are under `runs/pstnet_rgb_pilot/`: `training.json`, `plan.json`,
`report.md`, `learning_curve.png`, `validation_examples.png`, `validation_masks.npz`,
and `validation.json`. Checkpoints are under
`D:\Doktorat\Platforma\models\pstnet_rgb_pilot_v1`.
The qualitative examples were fixed before evaluating predictions.

## Implementation versus completed experiments

| Component | Implemented | Completed with own trained weights |
|---|---|---|
| RGB segmentation | Yes, with upstream numerical parity tests | Small pilot only |
| Original neural RGB+thermal fusion | Yes | No |
| Learned segmentation acquisition gate | Yes | No |
| Gated segmentation replay and evaluation | Yes | No |
| Historical binary presence experiments | Yes | Yes, separate task |

Published reference mIoU values are approximately 67.66% for RGB and 68.37% for
full fusion. They are not results from the small pilot or from this repository's
current trained fusion model. Original author checkpoints remain unavailable from
the links checked on 2026-10-17. See [PSTNet reproduction](PSTNET_REPRODUCTION.md).

## Next research work

1. Improve the own RGB baseline using more of the reserved vision-training pool;
   keep the existing family split and the acquisition holdout.
2. Train the original fusion stream with RGB weights and statistics frozen.
3. Freeze both vision models, collect acquisition supervision on separate recordings,
   and learn when thermal is useful.
4. Compare no acquisition, always acquire, uncertainty thresholds, random acquisition,
   and learned gain on the same frozen models and data protocol.

Report global class IoU together with image pulls, transferred bytes and measured
runtime. Keep original-checkpoint reproduction separate from own retraining and
from historical binary classification results.

## UrbanIng CoBEVT CPU smoke evaluation — 2026-10-23

The frozen official `CoBEVT_SIS_1_2_vs_3` checkpoint completed real-data offline
evaluation on 20 frames of `20241126_0017_crossing1_00`, with vehicle `100000` as
ego. The native release 1.0 sequence was downloaded and verified; the unchanged
official converter processed two bounded source views. Execution used Linux
x86_64, Python 3.12.14, CPU PyTorch 2.6.0 and two model threads. The model was not
retrained. See [protocol, dependencies and commands](URBANING_STAGE1.md).

Frames 1–10 contain only ego and infrastructure within the upstream 70m range.
Vehicle-class AP at BEV IoU 0.5 was **43.16%** for ego and **91.99%** with
infrastructure. There were no annotated 2Wheelers in this window, so four-class
macro AP is undefined and reported as null.

Frames 101–110 have all three sources available. Each row below uses the same
ground truth: 726 Vehicle, 31 Heavy_Vehicle, 19 2Wheeler and 100 Pedestrian
object annotations across frames. These are not counts of distinct tracks.

| Variant | BEV mAP @ IoU 0.5, four classes | Vehicle AP @ IoU 0.5 | Peer requests/frame |
|---|---:|---:|---:|
| Ego | 24.76% | 56.77% | 0 |
| Ego + vehicle | 36.14% | 73.88% | 1 |
| Ego + infrastructure | 47.53% | 81.16% | 1 |
| All sources | 53.21% | 90.81% | 2 |
| Random one peer | 42.04% | 77.20% | 1 |
| Entropy gate, threshold 0.5 | 42.04% | 77.20% | 1 |

The example entropy threshold requested one peer in every evaluated frame;
its outcome therefore equals random-one-peer here. This is **not evidence of an
effective adaptive stopping policy**. In the middle window, choosing one partner
halves request count relative to all sources, but no byte or latency saving was
measured. 2Wheeler AP remains weak even with cooperation.

These are **diagnostic results on one crossing1 recording**, not a held-out
benchmark, significance test or paper reproduction. The checkpoint's held-out
crossing is crossing3, which was not used. Threshold calibration, matched-budget
controls, recording-level evaluation, both ego vehicles, full test aggregation,
GPU execution and online replay remain follow-up work.

Local artifacts: `runs/urbaning-stage1-cpu-smoke-001/` and
`runs/urbaning-stage1-cpu-mid10-001/`. Each has configuration/provenance, native
associations, source hashes, per-action predictions, shared GT and metrics.
Raw data, model weights and run artifacts remain outside Git.

## Local run ledger

| Directory under `runs/` | Purpose |
|---|---|
| `pstnet_rgb_pilot/` | Own RGB segmentation pilot |
| `urbaning-stage1-cpu-smoke-001/` | Frozen CoBEVT, crossing1 frames 1–10, CPU |
| `urbaning-stage1-cpu-mid10-001/` | Frozen CoBEVT, crossing1 frames 101–110, CPU |
| `pstnet_reproduction/` | Upstream parity checks, full dataset audit and checkpoint availability |
| `pst900/` | Initial presence baseline and image audit |
| `pst900_cnn/` | Independent binary RGB/thermal CNN classifiers |
| `pst900_learning/` | Binary acquisition with Brier-gain targets |
| `pst900_learning_accuracy/` | Binary acquisition with classification-error targets |

`runs/` is local and Git-ignored. Historical reports retain their original language
and contents. Their earlier test subset was inspected during method development,
so those presence results are diagnostic, not a fresh confirmatory evaluation.
