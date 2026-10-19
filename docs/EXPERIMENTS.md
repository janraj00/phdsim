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

## Local run ledger

| Directory under `runs/` | Purpose |
|---|---|
| `pstnet_rgb_pilot/` | Own RGB segmentation pilot |
| `pstnet_reproduction/` | Upstream parity checks, full dataset audit and checkpoint availability |
| `pst900/` | Initial presence baseline and image audit |
| `pst900_cnn/` | Independent binary RGB/thermal CNN classifiers |
| `pst900_learning/` | Binary acquisition with Brier-gain targets |
| `pst900_learning_accuracy/` | Binary acquisition with classification-error targets |

`runs/` is local and Git-ignored. Historical reports retain their original language
and contents. Their earlier test subset was inspected during method development,
so those presence results are diagnostic, not a fresh confirmatory evaluation.
